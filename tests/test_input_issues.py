from __future__ import annotations

import pytest

from app import input_issues


def test_case_validator_messages_remain_separate_and_route_to_load_editors():
    issues = input_issues.case_issues(
        [
            "Plastic row 1: Name is required",
            "Elastic row 2: n_long_ed_kn must be a finite number",
            "Case name 'A' is duplicated; names must be unique",
        ]
    )

    assert [issue.message for issue in issues] == [
        "Plastic row 1: Name is required",
        "Elastic row 2: n_long_ed_kn must be a finite number",
        "Case name 'A' is duplicated; names must be unique",
    ]
    assert issues[0].target == input_issues.InputTarget(
        input_issues.LOADS,
        "plastic_cases_editor",
        "Plastic and capacity cases",
    )
    assert issues[1].target.widget_key == "elastic_cases_editor"
    assert issues[2].target.stage == input_issues.LOADS


def test_material_definition_routes_to_exact_family_and_unknowns_fail_safe():
    issues = input_issues.section_issues(
        {
            "section": object(),
            "material_definition_errors": (
                "M4: yield stress must be positive",
                "P2: elastic modulus must be positive",
            ),
        }
    )

    assert [issue.target.material_family for issue in issues] == [
        "Mild steel",
        "Prestressing steel",
    ]
    assert [issue.target.material_id for issue in issues] == ["M4", "P2"]
    unknown = input_issues.heightened_issues(
        ["A future validator message with no registered owner"]
    )[0]
    assert unknown.target is None


def test_target_registry_rejects_impossible_stage_family_combinations():
    with pytest.raises(ValueError, match="material-family destination"):
        input_issues.InputTarget(
            input_issues.LOADS,
            material_family="Concrete",
        )
    with pytest.raises(ValueError, match="material-ID destination"):
        input_issues.InputTarget(
            input_issues.MATERIAL_PARAMETERS,
            material_family="Mild steel",
            material_id="P2",
        )


def test_heightened_permitted_width_routes_to_schema25_global_setting():
    issue = input_issues.heightened_issues(
        ["Permitted crack width must be a positive finite number"]
    )[0]

    assert issue.target == input_issues.InputTarget(
        input_issues.ANALYSIS_SETTINGS,
        "sls_permitted_crack_width_mm",
        "Permitted crack width (shared)",
    )
