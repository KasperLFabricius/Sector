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


def test_heightened_permitted_width_routes_to_dedicated_setting():
    issue = input_issues.heightened_issues(
        ["Heightened permitted crack width must be a positive finite number"]
    )[0]

    assert issue.target == input_issues.InputTarget(
        input_issues.ANALYSIS_SETTINGS,
        "sls_heightened_permitted_crack_width_mm",
        "Heightened permitted crack width",
    )


@pytest.mark.parametrize(
    ("message", "stage", "widget_key"),
    [
        (
            "Heightened crack control requires Elastic analysis to be enabled",
            input_issues.ANALYSIS_SETTINGS,
            "mode",
        ),
        (
            "Heightened crack control requires the registered first-generation "
            "DK NA:2024 design basis",
            input_issues.ANALYSIS_SETTINGS,
            "sls_code",
        ),
        (
            "Heightened crack control requires at least one crack-enabled "
            "Elastic case",
            input_issues.LOADS,
            "elastic_cases_editor",
        ),
        (
            "Select one crack-enabled Elastic case as the heightened reference",
            input_issues.ANALYSIS_SETTINGS,
            "sls_heightened_reference_case",
        ),
        (
            "Fine-system effective tension area must be a positive finite number",
            input_issues.ANALYSIS_SETTINGS,
            "sls_heightened_fine_effective_tension_area_mm2",
        ),
        (
            "Coarse-system effective tension area must be a positive finite number",
            input_issues.ANALYSIS_SETTINGS,
            "sls_heightened_coarse_effective_tension_area_mm2",
        ),
    ],
)
def test_heightened_dual_inputs_route_to_current_correction_target(
    message,
    stage,
    widget_key,
):
    issue = input_issues.heightened_issues([message])[0]

    assert issue.target is not None
    assert issue.target.stage == stage
    assert issue.target.widget_key == widget_key


def test_removed_heightened_operands_do_not_receive_stale_navigation_targets():
    issues = input_issues.heightened_issues(
        [
            "Bar diameter must be a positive finite number",
            "Provided reinforcement area must be a positive finite number",
        ]
    )

    assert all(issue.target is None for issue in issues)
