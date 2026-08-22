"""Contracts for the shared manual/app information architecture."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from app import manual_information_architecture as ia  # noqa: E402
from app import table_field_definitions as fields  # noqa: E402

import manual  # noqa: E402


def test_input_stages_and_result_views_match_the_exact_application_contract():
    assert tuple(item.label for item in ia.INPUT_STAGES) == (
        "Analysis settings",
        "Section",
        "Material parameters",
        "Loads",
        "Project",
    )
    assert tuple(item.label for item in ia.WORKSPACES) == ("Report",)
    report = ia.destination("report-workspace")
    assert report.heading == "Report workspace"
    assert ia.heading_anchor("Report workspace", 2) == report.anchor
    assert "WORKSPACES" in ia.__all__
    assert tuple(item.label for item in ia.RESULT_VIEWS) == (
        "Results Overview",
        "Plastic Results",
        "N-M Interaction",
        "Elastic Results",
        "Fatigue Results",
        "Detailing",
        "Shear",
        "Torsion",
        "M-V-T Combined",
    )

    source = (ROOT / "app" / "sector_app.py").read_text("utf-8")
    assert "stage_labels = tuple(stage.label for stage in manual_ia.INPUT_STAGES)" in source
    assert "VIEWS = [view.label for view in manual_ia.RESULT_VIEWS]" in source


def test_destinations_are_frozen_slotted_unique_and_resolvable():
    destinations = ia.ALL_DESTINATIONS
    assert len({item.key for item in destinations}) == len(destinations)
    assert len({item.anchor for item in destinations}) == len(destinations)
    assert all(item.anchor.startswith("manual-") for item in destinations)
    assert all(ia.destination(item.key) is item for item in destinations)
    assert not hasattr(destinations[0], "__dict__")
    with pytest.raises(FrozenInstanceError):
        destinations[0].anchor = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="unknown manual destination"):
        ia.destination("missing")


def test_every_shared_destination_has_an_authored_manual_heading():
    headings = {
        str(block[1])
        for block in manual.manual_blocks()
        if block[0] in {"h1", "h2", "h3"}
    }
    assert {item.heading for item in ia.ALL_DESTINATIONS} <= headings


def test_required_workflow_and_troubleshooting_inventories_are_complete():
    assert tuple(item.key for item in ia.WORKFLOWS) == (
        "section-creation",
        "materials-reinforcement",
        "action-tables",
        "elastic-crack",
        "plastic-capacity",
        "fatigue",
        "detailing",
        "review-results",
        "save-load",
        "report-profile",
    )
    assert all(item.action.strip() for item in ia.WORKFLOWS)
    assert all(ia.destination(item.destination_key) for item in ia.WORKFLOWS)
    assert all(
        ia.warning_reference(item.warning_key) for item in ia.WORKFLOWS
    )
    assert tuple(ia.WARNING_REFERENCES) == tuple(item.key for item in ia.WARNINGS)
    with pytest.raises(ValueError, match="unknown manual warning"):
        ia.warning_reference("missing")


def test_crack_comparison_guidance_uses_independent_zero_value_contract():
    warning = ia.warning_reference("crack-criterion-missing")
    guidance = f"{warning.symptom} {warning.cause} {warning.correction}"
    for token in (
        "long-term or short-term permitted width",
        "0 mm",
        "positive value for that duration",
        "without comparison",
    ):
        assert token in guidance
    for retired in ("blank", "shared value"):
        assert retired not in guidance

    readme = " ".join(
        (ROOT / "README.md").read_text(encoding="utf-8").split()
    )
    for token in (
        "independent user-specified long-term and short-term criteria",
        "When an Elastic action requests crack width",
        "criterion of 0 mm",
        "duration-matched criterion source",
    ):
        assert token in readme
    for retired in ("If no criterion is entered", "criterion is entered"):
        assert retired not in readme

    manual_text = " ".join(
        item
        for block in manual.manual_blocks()
        for item in block
        if isinstance(item, str)
    )
    product_identity = (ROOT / "docs" / "product_identity.md").read_text(
        encoding="utf-8"
    )
    load_case_contract = (ROOT / "app" / "load_cases.py").read_text(
        encoding="utf-8"
    )
    assert "A 0 mm limit leaves only that duration's calculated width" in manual_text
    assert "crack-width-enabled Elastic row" in manual_text
    assert "Independent long-term and short-term crack-width limits" in manual_text
    assert "Independent long-term and short-term crack-width limits" in product_identity
    assert "Elastic action that requests crack width" in product_identity
    assert "0 mm value leaves that duration's calculated width" in product_identity
    assert "Independent long-term and short-term permitted" in load_case_contract

    current_publication = "\n".join(
        (guidance, readme, manual_text, product_identity, load_case_contract)
    ).casefold()
    for retired in (
        "with no criterion",
        "without a criterion",
        "if no criterion is entered",
        "if a criterion is entered",
        "optional user-specified crack-width criterion",
        "one optional positive permitted width",
        "blank ordinary crack criterion",
        "one optional permitted width in analysis settings is shared by",
        "shared by every ordinary and heightened crack check",
        "shared analysis permitted width",
        "supply the shared permitted width",
    ):
        assert retired not in current_publication


def test_workflow_actions_name_the_exact_user_route_and_no_generic_fallback():
    required_routes = {
        "section-creation": ("Inputs > Section", "preview"),
        "materials-reinforcement": (
            "Inputs > Material parameters",
            "Inputs > Section",
            "every used ID resolves",
        ),
        "action-tables": ("Inputs > Loads", "row error"),
        "elastic-crack": (
            "Inputs > Analysis settings",
            "Inputs > Loads",
            "Analysis > Elastic Results",
        ),
        "plastic-capacity": (
            "Inputs > Analysis settings",
            "Inputs > Loads",
            "Analysis > Plastic Results",
            "Analysis > N-M Interaction",
        ),
        "fatigue": (
            "Inputs > Analysis settings",
            "Inputs > Material parameters",
            "Inputs > Section",
            "Inputs > Loads",
            "Analysis > Fatigue Results",
        ),
        "detailing": (
            "Inputs > Analysis settings",
            "Inputs > Loads",
            "Check minimum reinforcement",
            "Analysis > Detailing",
        ),
        "review-results": (
            "Analysis > Results Overview",
            "View",
        ),
        "save-load": (
            "Inputs > Project",
            "Analysis > Results Overview",
            "Calculate",
        ),
        "report-profile": ("Report", "generate", "download"),
    }
    assert set(required_routes) == {item.key for item in ia.WORKFLOWS}
    for workflow in ia.WORKFLOWS:
        assert all(
            token in workflow.action
            for token in required_routes[workflow.key]
        )

    report_action = next(
        item.action for item in ia.WORKFLOWS if item.key == "report-profile"
    )
    assert "figure option" not in report_action.lower()

    for workflow in ia.WORKFLOWS:
        if "press Calculate" not in workflow.action:
            continue
        assert "Analysis >" in workflow.action
        assert workflow.action.index("Analysis >") < workflow.action.index(
            "press Calculate"
        )

    for warning in ia.WARNINGS:
        if "press Calculate" not in warning.correction:
            continue
        assert "Analysis >" in warning.correction
        assert warning.correction.index("Analysis >") < warning.correction.index(
            "press Calculate"
        )

    manual_text = "\n".join(str(block) for block in manual.manual_blocks())
    assert "calculate or review as applicable" not in manual_text
    assert "portable-build" not in manual_text


def test_results_overview_warning_routes_to_the_shared_review_entry():
    workflow = next(
        item for item in ia.WORKFLOWS if item.key == "review-results"
    )
    assert workflow.warning_key == "results-review"
    warning = ia.warning_reference("results-review")
    assert "Analysis > Results Overview" in warning.correction
    assert "global compliance verdict" in warning.correction

    source = (ROOT / "app" / "sector_app.py").read_text("utf-8")
    assert '"results-review"' in source

    assert "Inputs > Loads" in ia.warning_reference("loads-invalid").correction
    assert "report" not in ia.warning_reference(
        "results-stale"
    ).correction.casefold()
    report_stale = ia.warning_reference("report-stale").correction
    assert "Report" in report_stale
    assert "Generate report" in report_stale
    assert "If calculation inputs changed" in report_stale


def test_every_streamlit_warning_routes_through_the_manual_registry():
    source = (ROOT / "app" / "sector_app.py").read_text("utf-8")
    tree = ast.parse(source)
    warning_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "warning"
    ]
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_manual_warning"
    )
    helper_warning_calls = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "warning"
    ]
    assert warning_calls == helper_warning_calls

    routed = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_manual_warning"
    ]
    assert routed
    keys = []
    for call in routed:
        assert len(call.args) >= 3
        assert isinstance(call.args[1], ast.Constant)
        assert isinstance(call.args[1].value, str)
        keys.append(call.args[1].value)
    assert set(keys) <= set(ia.WARNING_REFERENCES)


def test_every_registered_warning_is_published_in_the_troubleshooting_table():
    expected_rows = [
        [warning.symptom, warning.cause, warning.correction]
        for warning in ia.WARNINGS
    ]
    matching = [
        block
        for block in manual.manual_blocks()
        if block[0] == "table"
        and block[1] == ["Symptom", "Likely cause", "Correction"]
    ]
    assert len(matching) == 1
    assert matching[0][2] == expected_rows


def test_every_editable_table_field_has_full_reference_metadata():
    expected = sum(len(fields.table_fields(key)) for key in fields.TABLE_KEYS)
    rows = manual.editable_field_reference_rows()
    assert len(rows) == expected
    assert all(len(row) == 5 for row in rows)
    assert all(all(str(cell).strip() for cell in row) for row in rows)

    for table_key in fields.TABLE_KEYS:
        for definition in fields.table_fields(table_key):
            assert fields.validation_rule(definition)
            assert fields.method_dependency(table_key, definition)


def test_heading_anchor_is_level_sensitive_for_duplicate_method_names():
    assert ia.heading_anchor("Grouped fatigue", 1) == "manual-method-fatigue"
    assert ia.heading_anchor("Grouped fatigue", 2) is None
    assert ia.heading_anchor("Fatigue results", 2) == "manual-fatigue-results"
