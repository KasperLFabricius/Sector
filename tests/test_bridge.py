import pandas as pd
import pathlib
import sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import bridge_analysis
import bridge_inputs
from sector import bridge


def _empty_bridge_input():
    return {
        "bridge_standard": bridge.COMPONENT_METHODS,
        bridge_inputs.BRITTLE_TABLE_KEY: bridge_inputs.empty_table(
            bridge_inputs.BRITTLE_TABLE_KEY
        ),
        bridge_inputs.BOX_WALL_TABLE_KEY: bridge_inputs.empty_table(
            bridge_inputs.BOX_WALL_TABLE_KEY
        ),
        bridge_inputs.MINIMUM_CRACK_TABLE_KEY: bridge_inputs.empty_table(
            bridge_inputs.MINIMUM_CRACK_TABLE_KEY
        ),
    }


def test_optional_brittle_method_b_remains_numerical_under_danish_selection():
    result = bridge.calculate_brittle_method_b(
        [
            bridge.PrestressBrittleRegion(
                "bottom",
                m_rep_knm=1000.0,
                z_s_m=0.8,
                f_yk_mpa=500.0,
                as_provided_mm2=3000.0,
            )
        ],
        selected_standard=bridge.EN1992_2_DK_NA,
    )

    assert result["rows"][0]["as_required_mm2"] == pytest.approx(2500.0)
    assert result["rows"][0]["utilisation"] == pytest.approx(5.0 / 6.0)
    assert result["rows"][0]["status"] == "PASS"
    assert "status" not in result
    assert "expects a different" in result["warning"]


def test_box_wall_benchmark_retains_actual_custom_angle_with_warning():
    result = bridge.calculate_box_walls(
        [
            bridge.BoxWall(
                "left",
                cot_theta=0.5,
                v_ed_kn=200.0,
                v_rd_max_kn=500.0,
                t_ed_equivalent_kn=50.0,
                t_rd_max_equivalent_kn=250.0,
            )
        ]
    )

    assert result["rows"][0]["cot_theta"] == pytest.approx(0.5)
    assert result["rows"][0]["utilisation"] == pytest.approx(0.6)
    assert result["rows"][0]["status"] == "PASS"
    assert "status" not in result
    assert any("actual values were retained" in item for item in result["warnings"])


def test_web_flange_minimum_crack_reinforcement_benchmark():
    result = bridge.calculate_minimum_crack_reinforcement(
        [
            bridge.MinimumCrackComponent(
                "web",
                act_mm2=100_000.0,
                k_c=0.4,
                k=0.8,
                fct_eff_mpa=3.0,
                sigma_s_mpa=200.0,
                as_provided_mm2=600.0,
            )
        ]
    )

    row = result["rows"][0]
    assert row["as_required_mm2"] == pytest.approx(480.0)
    assert row["utilisation"] == pytest.approx(0.8)
    assert row["status"] == "PASS"
    assert "status" not in result


def test_bridge_adapter_runs_only_nonempty_tables_without_coverage_rows():
    brittle = bridge_inputs.normalise_table(
        [{
            "region_id": "R1",
            "m_rep_knm": 100.0,
            "z_s_m": 0.5,
            "f_yk_mpa": 500.0,
            "as_provided_mm2": 500.0,
        }],
        bridge_inputs.BRITTLE_TABLE_KEY,
    )
    inp = {
        "bridge_standard": bridge.COMPONENT_METHODS,
        bridge_inputs.BRITTLE_TABLE_KEY: brittle,
        bridge_inputs.BOX_WALL_TABLE_KEY: bridge_inputs.empty_table(
            bridge_inputs.BOX_WALL_TABLE_KEY
        ),
        bridge_inputs.MINIMUM_CRACK_TABLE_KEY: bridge_inputs.empty_table(
            bridge_inputs.MINIMUM_CRACK_TABLE_KEY
        ),
    }

    payload = bridge_analysis.run(inp)

    assert set(payload["calculations"]) == {"brittle_method_b"}
    assert "coverage" not in payload
    assert "approval" not in str(payload).casefold()


def test_bridge_adapter_materialises_one_shot_table_once():
    inp = _empty_bridge_input()
    inp[bridge_inputs.BOX_WALL_TABLE_KEY] = (
        row
        for row in [{
            "wall_id": "W1",
            "cot_theta": 1.5,
            "v_ed_kn": 50.0,
            "v_rd_max_kn": 100.0,
            "t_ed_equivalent_kn": 10.0,
            "t_rd_max_equivalent_kn": 100.0,
        }]
    )

    payload = bridge_analysis.run(inp)

    assert payload["failures"] == ()
    row = payload["calculations"]["box_walls"]["rows"][0]
    assert row["wall_id"] == "W1"
    assert row["utilisation"] == pytest.approx(0.6)


def test_malformed_bridge_numeric_value_is_rejected():
    table = pd.DataFrame([{
        "wall_id": "W1",
        "cot_theta": "not numeric",
        "v_ed_kn": 1.0,
        "v_rd_max_kn": 2.0,
        "t_ed_equivalent_kn": 0.0,
        "t_rd_max_equivalent_kn": 2.0,
    }])

    with pytest.raises(ValueError, match="finite numeric"):
        bridge_inputs.records(table, bridge_inputs.BOX_WALL_TABLE_KEY)


def test_malformed_numeric_row_is_not_filtered_as_blank():
    table = pd.DataFrame([{
        "wall_id": None,
        "cot_theta": 1.5,
        "v_ed_kn": "not numeric",
        "v_rd_max_kn": 100.0,
        "t_ed_equivalent_kn": 0.0,
        "t_rd_max_equivalent_kn": 100.0,
    }])

    with pytest.raises(bridge.BridgeCalculationError) as caught:
        bridge_inputs.records(table, bridge_inputs.BOX_WALL_TABLE_KEY)

    assert caught.value.code == "INVALID_INPUT"
    assert caught.value.field == "v_ed_kn"


def test_bridge_boolean_type_is_pinned_before_calculation():
    table = pd.DataFrame([{
        "component": "web",
        "act_mm2": 1000.0,
        "k_c": 0.4,
        "k": 0.8,
        "fct_eff_mpa": 3.0,
        "sigma_s_mpa": 200.0,
        "as_provided_mm2": 100.0,
        "restrained_shrinkage": "yes",
    }])

    with pytest.raises(bridge.BridgeCalculationError) as caught:
        bridge_inputs.records(table, bridge_inputs.MINIMUM_CRACK_TABLE_KEY)

    assert caught.value.code == "INVALID_INPUT"
    assert caught.value.field == "restrained_shrinkage"


def test_truly_blank_bridge_row_remains_inert():
    assert bridge_inputs.records([{}], bridge_inputs.BOX_WALL_TABLE_KEY) == []


def test_duplicate_bridge_columns_are_rejected_before_normalisation():
    table = pd.DataFrame([["W1", "W2"]], columns=["wall_id", "wall_id"])

    with pytest.raises(bridge.BridgeCalculationError) as caught:
        bridge_inputs.records(table, bridge_inputs.BOX_WALL_TABLE_KEY)

    assert caught.value.code == "INVALID_INPUT"
    assert caught.value.field == bridge_inputs.BOX_WALL_TABLE_KEY
    assert "duplicate columns" in caught.value.message


@pytest.mark.parametrize(
    ("calculation", "field"),
    [
        (
            lambda: bridge.minimum_brittle_reinforcement_area(
                1.0,
                1.0e-200,
                1.0e-200,
            ),
            "As,min",
        ),
        (
            lambda: bridge.box_wall_interaction(
                1.0e308,
                1.0e-308,
                0.0,
                1.0,
            ),
            "wall VEd/VRd,max",
        ),
        (
            lambda: bridge.minimum_crack_reinforcement_area(
                1.0e308,
                1.0e308,
                1.0,
                1.0,
                1.0,
            ),
            "As,min",
        ),
    ],
)
def test_finite_inputs_never_publish_nonfinite_bridge_results(
    calculation,
    field,
):
    with pytest.raises(bridge.BridgeCalculationError) as caught:
        calculation()

    assert caught.value.code == "NON_FINITE_RESULT"
    assert caught.value.field == field
    assert "finite result" in caught.value.message


def test_typed_bridge_failure_preserves_input_cause():
    with pytest.raises(bridge.BridgeCalculationError) as caught:
        bridge.minimum_brittle_reinforcement_area(object(), 1.0, 1.0)

    assert caught.value.code == "INVALID_INPUT"
    assert caught.value.field == "Mrep"
    assert isinstance(caught.value.__cause__, TypeError)


def test_bridge_adapter_converts_only_typed_failure_to_invalid_payload():
    inp = _empty_bridge_input()
    inp[bridge_inputs.BRITTLE_TABLE_KEY] = bridge_inputs.normalise_table(
        [{
            "region_id": "R1",
            "m_rep_knm": 1.0,
            "z_s_m": 1.0e-200,
            "f_yk_mpa": 1.0e-200,
            "as_provided_mm2": 1.0,
        }],
        bridge_inputs.BRITTLE_TABLE_KEY,
    )
    inp[bridge_inputs.BOX_WALL_TABLE_KEY] = bridge_inputs.normalise_table(
        [{
            "wall_id": "W1",
            "cot_theta": 1.5,
            "v_ed_kn": 50.0,
            "v_rd_max_kn": 100.0,
            "t_ed_equivalent_kn": 10.0,
            "t_rd_max_equivalent_kn": 100.0,
        }],
        bridge_inputs.BOX_WALL_TABLE_KEY,
    )

    payload = bridge_analysis.run_or_invalid(inp)

    assert set(payload["calculations"]) == {"box_walls"}
    assert payload["calculations"]["box_walls"]["rows"][0][
        "utilisation"
    ] == pytest.approx(0.6)
    assert payload["failures"] == ({
        "state": "INVALID",
        "family": "brittle_method_b",
        "code": "NON_FINITE_RESULT",
        "field": "As,min",
        "message": "As,min could not be represented as a finite result",
        "cause_type": "BridgeCalculationError",
    },)
    assert "errors" not in payload


def test_bridge_adapter_does_not_conceal_unexpected_fault(monkeypatch):
    def unexpected_fault(*args, **kwargs):
        raise RuntimeError("unexpected bridge implementation fault")

    monkeypatch.setattr(bridge_inputs, "calculate_box_walls", unexpected_fault)

    with pytest.raises(RuntimeError, match="unexpected bridge implementation"):
        bridge_analysis.run_or_invalid(_empty_bridge_input())


def test_pr13a1_acceptance_contract_pins_scope_and_failure_semantics():
    text = " ".join((
        ROOT / "docs" / "pr13a1_f013_typed_bridge_boundary_acceptance.md"
    ).read_text(encoding="utf-8").split())

    for required in (
        "89fbc4a9713727093f453d0af7ffdce2dae17393",
        "Sector remains version `0.91`",
        "`INVALID_INPUT`",
        "`NON_FINITE_RESULT`",
        "unexpected implementation exception propagates unchanged",
        "A corrupt brittle family does not remove a valid box-wall",
        "No bridge coverage aggregate",
        "v0.93 change is included",
    ):
        assert required in text
