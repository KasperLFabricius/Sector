from __future__ import annotations

import pytest

from app import input_issues
from sector.engineer_message import EngineerMessage


def test_case_validator_messages_remain_separate_and_route_to_load_editors():
    issues = input_issues.case_issues(
        [
            EngineerMessage(
                "PLASTIC-CASE-NAME",
                "Enter a name for every active Plastic case",
            ),
            EngineerMessage(
                "ELASTIC-N-LONG",
                "Enter a finite sustained axial force in every active Elastic case",
            ),
            EngineerMessage(
                "CASE-NAME-UNIQUE",
                "Use a unique name for every Plastic and Elastic case",
            ),
        ]
    )

    assert [issue.message.text for issue in issues] == [
        "Enter a name for every active Plastic case",
        "Enter a finite sustained axial force in every active Elastic case",
        "Use a unique name for every Plastic and Elastic case",
    ]
    assert issues[0].target == input_issues.InputTarget(
        input_issues.LOADS,
        "plastic_cases_editor",
        "Plastic and capacity cases",
    )
    assert issues[1].target.widget_key == "elastic_cases_editor"
    assert issues[2].target.stage == input_issues.LOADS


@pytest.mark.parametrize(
    ("code", "widget_key", "widget_label"),
    (
        (
            "PLASTIC-SWEEP-BOUNDS",
            "v_max",
            "Neutral-axis sweep end angle",
        ),
        (
            "PLASTIC-SWEEP-INCREMENT",
            "v_inc",
            "Neutral-axis sweep maximum increment",
        ),
        (
            "PLASTIC-SWEEP-VALUES",
            None,
            "Neutral-axis sweep",
        ),
    ),
)
def test_plastic_sweep_issues_route_to_analysis_settings(
    code,
    widget_key,
    widget_label,
):
    issue = input_issues.case_issues(
        [EngineerMessage(code, "Correct the neutral-axis sweep")]
    )[0]

    assert issue.target == input_issues.InputTarget(
        input_issues.ANALYSIS_SETTINGS,
        widget_key,
        widget_label,
    )


def test_material_definition_routes_to_exact_family_and_unknowns_fail_safe():
    issues = input_issues.section_issues(
        {
            "section": object(),
            "material_definition_errors": (
                EngineerMessage(
                    "MILD-RUPTURE-STRESS",
                    "Enter a positive mild-steel ultimate strength",
                ),
                EngineerMessage(
                    "PRESTRESS-MODULUS",
                    "Enter a positive prestressing-steel modulus",
                ),
            ),
        }
    )

    assert [issue.target.material_family for issue in issues] == [
        "Mild steel",
        "Prestressing steel",
    ]
    assert [issue.target.material_id for issue in issues] == [None, None]
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
        [EngineerMessage(
            "HEIGHTENED-CRACK-LIMIT",
            "Enter a positive finite heightened crack-width limit",
        )]
    )[0]

    assert issue.target == input_issues.InputTarget(
        input_issues.ANALYSIS_SETTINGS,
        "sls_heightened_permitted_crack_width_mm",
        "Heightened permitted crack width",
    )


@pytest.mark.parametrize(
    ("code", "message", "stage", "widget_key"),
    [
        (
            "HEIGHTENED-ELASTIC-MODE",
            "Heightened crack control requires Elastic analysis to be enabled",
            input_issues.ANALYSIS_SETTINGS,
            "mode",
        ),
        (
            "HEIGHTENED-DESIGN-BASIS",
            "Heightened crack control is available only with the first-generation "
            "DK NA:2024 design basis",
            input_issues.ANALYSIS_SETTINGS,
            "sls_code",
        ),
        (
            "HEIGHTENED-REFERENCE-REQUIRED",
            "Heightened crack control requires at least one crack-enabled "
            "Elastic case",
            input_issues.LOADS,
            "elastic_cases_editor",
        ),
        (
            "HEIGHTENED-REFERENCE-SELECT",
            "Select one crack-enabled Elastic case as the heightened reference",
            input_issues.ANALYSIS_SETTINGS,
            "sls_heightened_reference_case",
        ),
        (
            "HEIGHTENED-FINE-AREA",
            "Fine-system effective tension area must be a positive finite number",
            input_issues.ANALYSIS_SETTINGS,
            "sls_heightened_fine_effective_tension_area_mm2",
        ),
        (
            "HEIGHTENED-COARSE-AREA",
            "Coarse-system effective tension area must be a positive finite number",
            input_issues.ANALYSIS_SETTINGS,
            "sls_heightened_coarse_effective_tension_area_mm2",
        ),
    ],
)
def test_heightened_dual_inputs_route_to_current_correction_target(
    code,
    message,
    stage,
    widget_key,
):
    issue = input_issues.heightened_issues([
        EngineerMessage(code, message)
    ])[0]

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


def test_arbitrary_section_and_assignment_diagnostics_fail_closed_and_log(caplog):
    hostile = (
        "RAW-INPUT GitHub PR #98 SHA-256 payload schema contract "
        "internal_private_ID EQ-INPUT-7"
    )
    issues = input_issues.section_issues(
        {
            "section": object(),
            "geometry_error": hostile,
            "void_error": hostile,
            "steel_error": hostile,
            "material_assignment_errors": (hostile,),
            "material_definition_errors": (hostile,),
            "torsion_gamma_ct_error": hostile,
            "material_error": hostile,
        }
    )
    visible = " ".join(issue.message.text for issue in issues)

    assert hostile not in visible
    assert "Review the concrete outline and void geometry" in visible
    assert "Keep every void inside the outline" in visible
    assert "Place every reinforcement element inside the concrete" in visible
    assert "Select a defined material for every reinforcement" in visible
    assert "Review the selected material values" in visible
    assert "Enter a positive finite concrete tensile factor gamma_ct" in visible
    assert caplog.text.count("Suppressed untrusted diagnostic") == 6
    assert hostile in caplog.text
