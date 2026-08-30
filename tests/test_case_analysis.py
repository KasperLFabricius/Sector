"""Typed multi-case orchestration tests independent of Streamlit."""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import case_analysis  # noqa: E402
import load_cases  # noqa: E402
from sector import capacity  # noqa: E402


def _plastic(rows):
    return load_cases.normalise_table(rows, load_cases.PLASTIC_TABLE_KEY)


def _elastic(rows):
    return load_cases.normalise_table(rows, load_cases.ELASTIC_TABLE_KEY)


def _base(**overrides):
    base = {
        "mode": "Both",
        "shear_on": True,
        "torsion_on": True,
        "combined_on": True,
        "sls_long_term_permitted_crack_width_mm": 0.0,
        "sls_short_term_permitted_crack_width_mm": 0.0,
        "sls_heightened_permitted_crack_width_mm": 0.0,
        "plastic_cases": _plastic([
            {
                "name": "PL-A",
                "description": "Signed actions",
                "n_ed_kn": -500.0,
                "mx_ed_knm": -120.0,
                "my_ed_knm": 35.0,
                "vx_ed_kn": -40.0,
                "vx_face": "negative",
                "t_ed_knm": 0.0,
            },
            {
                "name": "PL-B",
                "description": "Combined actions",
                "n_ed_kn": 25.0,
                "mx_ed_knm": 80.0,
                "my_ed_knm": -15.0,
                "vx_ed_kn": 30.0,
                "vy_ed_kn": -12.0,
                "vx_face": "positive",
                "t_ed_knm": -8.0,
            },
        ]),
        "elastic_cases": _elastic([
            {
                "name": "EL-STRESS",
                "description": "Characteristic stresses",
                "n_long_ed_kn": -100.0,
                "mx_long_ed_knm": 45.0,
                "my_long_ed_knm": -5.0,
                "n_short_ed_kn": 10.0,
                "mx_short_ed_knm": 20.0,
                "my_short_ed_knm": 3.0,
                "calculate_crack_width": False,
            },
            {
                "name": "EL-CRACK",
                "description": "Frequent crack width",
                "mx_long_ed_knm": 35.0,
                "mx_short_ed_knm": 8.0,
                "calculate_crack_width": True,
            },
        ]),
    }
    base.update(overrides)
    return base


def test_maps_signed_cases_flags_and_zero_capacity_actions():
    calls = []

    def runner(inp, *, reuse_plastic=None):
        assert reuse_plastic is None
        calls.append(inp)
        if inp["mode"] == "Elastic":
            return {"elastic": {"id": inp["elastic_case"]["id"]}}
        result = {"plastic": {"id": inp["plastic_case"]["id"]}}
        if inp["shear_on"]:
            result["shear"] = {"v_ed": inp["shear_V"]}
        if inp["torsion_on"]:
            result["torsion"] = {"t_ed": inp["torsion_T"]}
        if inp["combined_on"]:
            result["combined"] = {"active": True}
        return result

    result = case_analysis.run_case_tables(_base(), runner)

    assert [entry["name"] for entry in result["plastic_cases"]] == [
        "PL-A", "PL-B"
    ]
    assert [entry["name"] for entry in result["elastic_cases"]] == [
        "EL-STRESS", "EL-CRACK"
    ]
    pl_a, pl_b, el_stress, el_crack = calls
    assert (pl_a["P_pl"], pl_a["Mx_pl"], pl_a["My_pl"]) == (
        -500.0, -120.0, 35.0
    )
    assert pl_a["shear_V"] == 40.0
    assert pl_a["shear_Vx"] == -40.0
    assert pl_a["shear_Vy"] == 0.0
    assert pl_a["shear_components"]["vx"]["signed_v_ed"] == -40.0
    assert pl_a["shear_face_x"] == "negative"
    assert pl_a["shear_on"] is True
    assert pl_a["torsion_on"] is False
    assert pl_a["combined_on"] is False
    assert result["plastic_cases"][0]["actions"]["vx_ed_kn"] == -40.0
    assert pl_b["shear_Vx"] == 30.0 and pl_b["shear_Vy"] == -12.0
    assert pl_b["torsion_T"] == 8.0
    assert pl_b["combined_on"] is True
    assert el_stress["sls_cw"] is False
    assert el_crack["sls_cw"] is True
    assert result["plastic"]["id"] == "PL-A"
    assert result["elastic"]["id"] == "EL-STRESS"


def test_plastic_cases_keep_separate_torsion_authority_by_case_name():
    mapping = {
        "PL-A": {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_DESIGN_EQUILIBRIUM
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED,
        },
        "PL-B": {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_DESIGN_COMPATIBILITY_MEMBER
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_OPEN,
        },
    }
    base = _base(**{capacity.TORSION_CASE_AUTHORITIES_KEY: mapping})
    records = case_analysis.case_records(base, "plastic")
    first, second = (
        case_analysis.plastic_case_input(base, record) for record in records
    )

    assert first["torsion_design_basis"] == capacity.TORSION_DESIGN_EQUILIBRIUM
    assert first["torsion_member_scope"] == capacity.TORSION_MEMBER_CLOSED
    assert second["torsion_design_basis"] == (
        capacity.TORSION_DESIGN_COMPATIBILITY_MEMBER
    )
    assert second["torsion_member_scope"] == capacity.TORSION_MEMBER_OPEN

    reordered = list(reversed(records))
    assert case_analysis.plastic_case_input(
        base, reordered[0]
    )["torsion_design_basis"] == capacity.TORSION_DESIGN_COMPATIBILITY_MEMBER
    assert case_analysis.case_signature(
        records[0], load_cases.PLASTIC_TABLE_KEY, base
    ) != case_analysis.case_signature(
        records[1], load_cases.PLASTIC_TABLE_KEY, base
    )
    changed_mapping = {
        **mapping,
        "PL-A": {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED,
        },
    }
    changed_base = {
        **base,
        capacity.TORSION_CASE_AUTHORITIES_KEY: changed_mapping,
    }
    assert case_analysis.case_signature(
        records[0], load_cases.PLASTIC_TABLE_KEY, base
    ) != case_analysis.case_signature(
        records[0], load_cases.PLASTIC_TABLE_KEY, changed_base
    )
    assert case_analysis.case_signature(
        records[1], load_cases.PLASTIC_TABLE_KEY, base
    ) == case_analysis.case_signature(
        records[1], load_cases.PLASTIC_TABLE_KEY, changed_base
    )


@pytest.mark.parametrize(
    "authorities",
    (
        None,
        True,
        {"PL-B": True},
        {
            "PL-B": {
                capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                    capacity.TORSION_DESIGN_EQUILIBRIUM
                ),
                capacity.TORSION_CASE_MEMBER_SCOPE_KEY: True,
            }
        },
        {
            "PL-B": {
                capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                    capacity.TORSION_DESIGN_EQUILIBRIUM
                ),
                capacity.TORSION_CASE_MEMBER_SCOPE_KEY: (
                    capacity.TORSION_MEMBER_CLOSED
                ),
                "extra": "ignored",
            }
        },
    ),
)
def test_missing_or_malformed_case_authority_never_uses_global_fallback(
    authorities,
):
    base = _base(
        torsion_design_basis=capacity.TORSION_DESIGN_EQUILIBRIUM,
        torsion_member_scope=capacity.TORSION_MEMBER_CLOSED,
        **{capacity.TORSION_CASE_AUTHORITIES_KEY: authorities},
    )
    record = case_analysis.case_records(base, "plastic")[1]
    mapped = case_analysis.plastic_case_input(base, record)

    assert mapped["torsion_design_basis"] == (
        capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
    )
    assert mapped["torsion_member_scope"] == (
        capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
    )


def test_capacity_only_zero_action_case_is_recorded_but_not_run():
    calls = []
    inp = _base(
        mode="Elastic",
        torsion_on=False,
        combined_on=False,
        plastic_cases=_plastic([{"name": "PL-ZERO", "vy_ed_kn": 0.0}]),
        elastic_cases=_elastic([{"name": "EL-01"}]),
    )

    result = case_analysis.run_case_tables(
        inp,
        lambda case_inp, **_kwargs: calls.append(case_inp) or {"elastic": {}},
    )

    assert result["plastic_cases"][0]["evaluated"] is False
    assert result["plastic_cases"][0]["results"] == {}
    assert "shear" not in result
    assert len(calls) == 1
    assert calls[0]["mode"] == "Elastic"


def test_transverse_detailing_runs_only_for_active_reinforced_actions():
    base = _base(
        transverse_detailing_on=True,
        shear_links=True,
        combined_on=False,
    )
    first, second = [
        case_analysis.plastic_case_input(base, record)
        for record in case_analysis.case_records(base, "plastic")
    ]
    assert first["transverse_detailing_on"] is True
    assert second["transverse_detailing_on"] is True

    zero = case_analysis.plastic_case_input(
        base,
        {
            "name": "PL-ZERO",
            "description": "",
            "n_ed_kn": 0.0,
            "mx_ed_knm": 0.0,
            "my_ed_knm": 0.0,
            "vx_ed_kn": 0.0,
            "vy_ed_kn": 0.0,
            "vx_face": "auto",
            "vy_face": "auto",
            "t_ed_knm": 0.0,
            "check_minimum_reinforcement": False,
        },
    )
    assert zero["transverse_detailing_on"] is False


def test_transverse_detailing_keeps_active_shear_without_links_for_requirement_check():
    base = _base(
        transverse_detailing_on=True,
        shear_links=False,
        shear_on=True,
        torsion_on=False,
        combined_on=False,
    )
    record = case_analysis.case_records(base, "plastic")[0]
    mapped = case_analysis.plastic_case_input(base, record)
    assert mapped["shear_on"] is True
    assert mapped["transverse_detailing_on"] is True


def test_selected_minimum_reinforcement_row_runs_without_plastic_bending():
    calls = []
    inp = _base(
        mode="Elastic",
        shear_on=False,
        torsion_on=False,
        combined_on=False,
        minimum_reinforcement_on=True,
        plastic_cases=_plastic([
            {
                "name": "PL-MIN",
                "mx_ed_knm": 55.0,
                "check_minimum_reinforcement": True,
            },
            {
                "name": "PL-SKIP",
                "mx_ed_knm": 75.0,
                "check_minimum_reinforcement": False,
            },
        ]),
        elastic_cases=_elastic([{"name": "EL-01"}]),
    )

    def runner(case_inp, **_kwargs):
        calls.append(case_inp)
        if case_inp["mode"] == "Elastic":
            return {"elastic": {"case": case_inp["elastic_case"]["id"]}}
        assert case_inp["mode"] == "Capacity"
        assert case_inp["minimum_reinforcement_on"] is True
        return {"minimum_reinforcement": {"status": "PASS"}}

    result = case_analysis.run_case_tables(inp, runner)

    assert [call["mode"] for call in calls] == ["Capacity", "Elastic"]
    assert result["plastic_cases"][0]["evaluated"] is True
    assert result["plastic_cases"][0]["results"]["minimum_reinforcement"][
        "status"
    ] == "PASS"
    assert result["plastic_cases"][1]["evaluated"] is False


def test_reuses_unchanged_rows_and_recalculates_only_changed_row():
    calls = []

    def runner(inp, *, reuse_plastic=None):
        assert reuse_plastic is None
        calls.append(inp["plastic_case"]["id"])
        return {"plastic": {"mx": inp["Mx_pl"]}}

    first_inp = _base(
        mode="Plastic",
        shear_on=False,
        torsion_on=False,
        combined_on=False,
        elastic_cases=load_cases.empty_table(load_cases.ELASTIC_TABLE_KEY),
    )
    first = case_analysis.run_case_tables(first_inp, runner)
    assert calls == ["PL-A", "PL-B"]

    changed = first_inp.copy()
    changed["plastic_cases"] = _plastic([
        first_inp["plastic_cases"].iloc[0].to_dict(),
        {
            **first_inp["plastic_cases"].iloc[1].to_dict(),
            "mx_ed_knm": 81.0,
        },
    ])
    calls.clear()
    second = case_analysis.run_case_tables(
        changed,
        runner,
        reuse_plastic=first["plastic_cases"],
    )

    assert calls == ["PL-B"]
    assert second["plastic_cases"][0]["reused"] is True
    assert second["plastic_cases"][1]["reused"] is False
    assert second["plastic_cases"][1]["results"]["plastic"]["mx"] == 81.0


def test_capacity_change_reuses_matching_plastic_bending_subresult():
    seen_reuse = []

    def runner(inp, *, reuse_plastic=None):
        seen_reuse.append(reuse_plastic)
        plastic = reuse_plastic or {"token": len(seen_reuse)}
        return {"plastic": plastic, "shear": {"v_ed": inp["shear_V"]}}

    first_inp = _base(
        mode="Plastic",
        torsion_on=False,
        combined_on=False,
        plastic_cases=_plastic([
            {"name": "PL-A", "mx_ed_knm": 50.0, "vy_ed_kn": 20.0},
        ]),
        elastic_cases=load_cases.empty_table(load_cases.ELASTIC_TABLE_KEY),
    )
    first = case_analysis.run_case_tables(first_inp, runner)
    changed = first_inp.copy()
    changed["plastic_cases"] = _plastic([
        {"name": "PL-A", "mx_ed_knm": 50.0, "vy_ed_kn": 30.0},
    ])

    seen_reuse.clear()
    second = case_analysis.run_case_tables(
        changed,
        runner,
        reuse_plastic_bending=first["plastic_cases"],
    )

    assert seen_reuse == [{"token": 1}]
    assert second["plastic"]["token"] == 1
    assert second["shear"]["v_ed"] == 30.0


def test_rejects_names_duplicated_across_solver_tables():
    inp = _base(
        plastic_cases=_plastic([{"name": "CASE-1"}]),
        elastic_cases=_elastic([{"name": "case-1"}]),
    )

    with pytest.raises(case_analysis.EngineerValidationError) as caught:
        case_analysis.run_case_tables(inp, lambda _inp, **_kwargs: {})

    assert caught.value.engineer_message.code == "CASE-NAME-UNIQUE"
    assert caught.value.engineer_message.text == (
        "Use a unique name for every Plastic and Elastic case"
    )


@pytest.mark.parametrize(
    ("updates", "code", "text"),
    (
        (
            {"v_min": 100.0, "v_max": 0.0, "v_inc": 30.0},
            "PLASTIC-SWEEP-BOUNDS",
            "Set the neutral-axis sweep end angle equal to or greater than the "
            "start angle",
        ),
        (
            {"v_min": np.bool_(True), "v_max": 100.0, "v_inc": 30.0},
            "PLASTIC-SWEEP-VALUES",
            "Enter finite start, end and increment values for the neutral-axis "
            "sweep",
        ),
        (
            {"v_min": 0.0, "v_max": 100.0, "v_inc": 0.0},
            "PLASTIC-SWEEP-INCREMENT",
            "Enter a positive maximum increment for the neutral-axis sweep",
        ),
        (
            {"v_min": 0.0, "v_max": 1.0, "v_inc": 1e-20},
            "PLASTIC-SWEEP-RESOLUTION",
            "Increase the neutral-axis sweep maximum increment; the requested "
            "sweep is too fine to calculate reliably",
        ),
        (
            {"v_min": 1e16, "v_max": 1e16 + 2.0, "v_inc": 1.0},
            "PLASTIC-SWEEP-RESOLUTION",
            "Increase the neutral-axis sweep maximum increment; the requested "
            "sweep is too fine to calculate reliably",
        ),
        (
            {"v_min": 0.0, "v_max": 1e308, "v_inc": 1e-308},
            "PLASTIC-SWEEP-RESOLUTION",
            "Increase the neutral-axis sweep maximum increment; the requested "
            "sweep is too fine to calculate reliably",
        ),
        (
            {"v_min": -1e308, "v_max": 1e308, "v_inc": 1.0},
            "PLASTIC-SWEEP-SPAN",
            "Correct the neutral-axis sweep start and end angles; their separation "
            "is too large to calculate reliably",
        ),
    ),
)
def test_invalid_plastic_sweep_blocks_case_runner_with_authored_guidance(
    updates,
    code,
    text,
):
    inp = _base(**updates)
    calls = []

    with pytest.raises(case_analysis.EngineerValidationError) as caught:
        case_analysis.run_case_tables(
            inp,
            lambda *_args, **_kwargs: calls.append(True),
        )

    assert calls == []
    assert caught.value.engineer_message.code == code
    assert caught.value.engineer_message.text == text


def test_zero_span_plastic_sweep_remains_valid_for_case_orchestration():
    inp = _base(v_min=45.0, v_max=45.0, v_inc=30.0)

    assert not any(
        error.code.startswith("PLASTIC-SWEEP")
        for error in case_analysis.validation_errors(inp)
    )


def test_elastic_case_maps_both_analysis_criteria_and_sources():
    record = case_analysis.case_records(
        {
            "elastic_cases": _elastic([{
                "name": "EL-frequent",
                "calculate_crack_width": True,
            }])
        },
        "elastic",
    )[0]

    mapped = case_analysis.elastic_case_input(
        _base(
            sls_long_term_permitted_crack_width_mm=0.25,
            sls_short_term_permitted_crack_width_mm=0.30,
        ),
        record,
    )

    assert mapped["sls_long_term_permitted_crack_width_mm"] == pytest.approx(
        0.25
    )
    assert mapped["sls_short_term_permitted_crack_width_mm"] == pytest.approx(
        0.30
    )
    assert mapped["sls_long_term_permitted_crack_width_source"] == (
        "User input - Analysis settings - long-term"
    )
    assert mapped["sls_short_term_permitted_crack_width_source"] == (
        "User input - Analysis settings - short-term"
    )


def test_each_crack_width_input_changes_elastic_signature_and_reuse_boundary():
    calls = []

    def runner(case_inp):
        calls.append((
            case_inp["sls_long_term_permitted_crack_width_mm"],
            case_inp["sls_short_term_permitted_crack_width_mm"],
            case_inp["sls_heightened_permitted_crack_width_mm"],
        ))
        return {
            "elastic": {
                "crack_output": {
                    "long_term": {
                        "value": 0.20,
                        "case": "Long-term",
                        "governing": "R1",
                        "unit": "mm",
                    },
                    "short_term": {
                        "value": 0.24,
                        "case": "Short-term",
                        "governing": "R1",
                        "unit": "mm",
                    },
                }
            }
        }

    def inputs(long_term, short_term, heightened):
        return _base(
            mode="Elastic",
            shear_on=False,
            torsion_on=False,
            combined_on=False,
            sls_long_term_permitted_crack_width_mm=long_term,
            sls_short_term_permitted_crack_width_mm=short_term,
            sls_heightened_permitted_crack_width_mm=heightened,
            plastic_cases=load_cases.empty_table(
                load_cases.PLASTIC_TABLE_KEY
            ),
            elastic_cases=_elastic([{
                "name": "EL-one",
                "calculate_crack_width": True,
            }]),
        )

    first = case_analysis.run_case_tables(inputs(0.25, 0.30, 0.20), runner)
    second = case_analysis.run_case_tables(
        inputs(0.25, 0.40, 0.20), runner, reuse_elastic=first["elastic_cases"]
    )
    third = case_analysis.run_case_tables(
        inputs(0.25, 0.40, 0.21), runner, reuse_elastic=second["elastic_cases"]
    )

    assert calls == [
        (0.25, 0.30, 0.20),
        (0.25, 0.40, 0.20),
        (0.25, 0.40, 0.21),
    ]
    assert first["elastic_cases"][0]["signature"] != (
        second["elastic_cases"][0]["signature"]
    )
    assert second["elastic_cases"][0]["reused"] is False
    assert second["elastic_cases"][0]["signature"] != (
        third["elastic_cases"][0]["signature"]
    )


def test_case_orchestration_publishes_only_duration_matched_comparisons():
    inp = _base(
        mode="Elastic",
        shear_on=False,
        torsion_on=False,
        combined_on=False,
        sls_long_term_permitted_crack_width_mm=0.40,
        sls_short_term_permitted_crack_width_mm=0.30,
        plastic_cases=load_cases.empty_table(load_cases.PLASTIC_TABLE_KEY),
        elastic_cases=_elastic([{
            "name": "EL-governing",
            "calculate_crack_width": True,
        }]),
    )

    result = case_analysis.run_case_tables(
        inp,
        lambda _case_inp: {
            "elastic": {
                "crack_output": {
                    "long_term": {
                        "value": 0.36,
                        "case": "Long-term",
                        "governing": "R5",
                        "unit": "mm",
                    },
                    "short_term": {
                        "value": 0.36,
                        "case": "Short-term",
                        "governing": "R7",
                        "unit": "mm",
                    },
                }
            }
        },
    )
    output = result["elastic_cases"][0]["results"]["elastic"][
        "crack_output"
    ]

    assert output["long_term"]["calculation_state"] == (
        "WITHIN USER-SPECIFIED LIMIT"
    )
    assert output["long_term"]["ratio"] == pytest.approx(0.9)
    assert output["short_term"]["calculation_state"] == (
        "EXCEEDS USER-SPECIFIED LIMIT"
    )
    assert output["short_term"]["ratio"] == pytest.approx(1.2)
    assert output["short_term"]["criterion_source"] == (
        "User input - Analysis settings - short-term"
    )
    assert output["short_term"]["comparison_equation"] == (
        "w_k / w_k,criterion"
    )
    assert "status" not in output


def test_stored_criterion_is_not_assessed_when_width_was_not_requested():
    inp = _base(
        mode="Elastic",
        shear_on=False,
        torsion_on=False,
        combined_on=False,
        sls_long_term_permitted_crack_width_mm=0.25,
        sls_short_term_permitted_crack_width_mm=0.30,
        plastic_cases=load_cases.empty_table(load_cases.PLASTIC_TABLE_KEY),
        elastic_cases=_elastic([{
            "name": "EL-stored",
            "calculate_crack_width": False,
        }]),
    )

    result = case_analysis.run_case_tables(
        inp, lambda _case_inp: {"elastic": {}}
    )
    output = result["elastic"]["crack_output"]

    assert output["long_term"]["calculation_state"] == "NOT REQUESTED"
    assert output["short_term"]["calculation_state"] == "NOT REQUESTED"
    assert output["long_term"]["criterion_mm"] == pytest.approx(0.25)
    assert output["short_term"]["criterion_mm"] == pytest.approx(0.30)
    assert output["long_term"]["value"] is None
    assert output["short_term"]["value"] is None
