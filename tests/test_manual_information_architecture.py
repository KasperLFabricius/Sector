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
        "Project & report",
    )
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
        "portable-build",
    )
    assert all(ia.destination(item.destination_key) for item in ia.WORKFLOWS)
    assert all(
        ia.warning_reference(item.warning_key) for item in ia.WORKFLOWS
    )
    assert tuple(ia.WARNING_REFERENCES) == tuple(item.key for item in ia.WARNINGS)
    with pytest.raises(ValueError, match="unknown manual warning"):
        ia.warning_reference("missing")


def test_portable_workflow_names_the_real_double_click_and_unsigned_boundary():
    workflow = next(item for item in ia.WORKFLOWS if item.key == "portable-build")
    warning = ia.warning_reference(workflow.warning_key)
    assert workflow.action is not None
    combined = (
        f"{workflow.prerequisite} {workflow.expected_state} {workflow.action} "
        f"{warning.symptom} {warning.cause} {warning.correction}"
    )
    for token in (
        "official Sector source ZIP",
        "SHA-256",
        "64-bit CPython 3.13.0",
        "BUILD_SECTOR_PORTABLE.bat",
        "administrator",
        "portable ZIP",
        "Sector.exe alone",
        "SmartScreen",
        "README-PORTABLE.txt",
    ):
        assert token in combined

    manual_text = "\n".join(str(block) for block in manual.manual_blocks())
    assert workflow.action in manual_text


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
