"""Typed multi-case orchestration tests independent of Streamlit."""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import case_analysis  # noqa: E402
import load_cases  # noqa: E402


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
        "sls_conc_limit_pct": 60.0,
        "sls_steel_limit_pct": 80.0,
        "sls_pre_limit_pct": 75.0,
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
                "check_stress": True,
                "check_crack_width": False,
            },
            {
                "name": "EL-CRACK",
                "description": "Frequent crack width",
                "mx_long_ed_knm": 35.0,
                "mx_short_ed_knm": 8.0,
                "check_stress": False,
                "check_crack_width": True,
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
    assert el_stress["sls_conc_limit_pct"] == 60.0
    assert el_crack["sls_cw"] is True
    assert el_crack["sls_conc_limit_pct"] == 0.0
    assert el_crack["sls_steel_limit_pct"] == 0.0
    assert result["plastic"]["id"] == "PL-A"
    assert result["elastic"]["id"] == "EL-STRESS"


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

    with pytest.raises(ValueError, match="duplicated"):
        case_analysis.run_case_tables(inp, lambda _inp, **_kwargs: {})
