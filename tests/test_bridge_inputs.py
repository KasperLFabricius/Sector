import math

import pandas as pd
import pytest

from app import bridge_inputs
from sector import bridge, conformance


def test_default_coverage_table_has_one_fixed_row_per_decision():
    frame = bridge_inputs.empty_table(bridge_inputs.COVERAGE_TABLE_KEY)

    assert list(frame["check_id"]) == list(bridge.APPLICABILITY_CHECK_IDS)
    assert set(frame["applicability"]) == {bridge.NOT_ESTABLISHED}
    assert bridge_inputs.table_errors(
        frame, bridge_inputs.COVERAGE_TABLE_KEY
    ) == []


def test_bridge_table_records_round_trip_text_numeric_and_boolean_fields():
    original = pd.DataFrame([{
        "component": "Web",
        "act_mm2": 100_000.0,
        "k_c": 0.4,
        "k": 1.0,
        "fct_eff_mpa": 2.5,
        "sigma_s_mpa": 300.0,
        "as_provided_mm2": 500.0,
        "restrained_shrinkage": True,
        "parameter_basis": conformance.STANDARD_BASIS,
        "custom_methodology": "",
        "approval_reference": "",
    }])

    records = bridge_inputs.table_records(
        original,
        bridge_inputs.MINIMUM_TABLE_KEY,
    )
    restored = bridge_inputs.table_from_records(
        records,
        bridge_inputs.MINIMUM_TABLE_KEY,
    )

    assert records == [{
        "component": "Web",
        "act_mm2": 100_000.0,
        "k_c": 0.4,
        "k": 1.0,
        "fct_eff_mpa": 2.5,
        "sigma_s_mpa": 300.0,
        "as_provided_mm2": 500.0,
        "restrained_shrinkage": True,
        "parameter_basis": conformance.STANDARD_BASIS,
        "custom_methodology": "",
        "approval_reference": "",
    }]
    assert restored.to_dict("records") == records


@pytest.mark.parametrize(
    ("key", "record", "expected"),
    [
        (
            bridge_inputs.BRITTLE_TABLE_KEY,
            {
                "region_id": "Bottom",
                "m_rep_knm": True,
                "z_s_m": 0.5,
                "f_yk_mpa": 500.0,
                "as_provided_mm2": 1200.0,
            },
            "m_rep_knm must be finite",
        ),
        (
            bridge_inputs.BOX_WALL_TABLE_KEY,
            {
                "wall_id": "Top",
                "cot_theta": float("inf"),
                "v_ed_kn": 10.0,
                "v_rd_max_kn": 20.0,
                "t_ed_equivalent_kn": 10.0,
                "t_rd_max_equivalent_kn": 20.0,
            },
            "cot_theta must be finite",
        ),
        (
            bridge_inputs.MINIMUM_TABLE_KEY,
            {
                "component": "Web",
                "act_mm2": 100.0,
                "k_c": 0.4,
                "k": 1.0,
                "fct_eff_mpa": 2.9,
                "sigma_s_mpa": 300.0,
                "as_provided_mm2": 100.0,
                "restrained_shrinkage": "maybe",
            },
            "restrained_shrinkage must be Boolean",
        ),
    ],
)
def test_malformed_bridge_table_evidence_is_rejected_at_save_boundary(
    key,
    record,
    expected,
):
    errors = bridge_inputs.table_errors([record], key)

    assert any(expected in error for error in errors)
    with pytest.raises(ValueError, match=expected):
        bridge_inputs.table_records([record], key)


def _box_wall_record(cot_theta):
    return {
        "wall_id": "Wall",
        "cot_theta": cot_theta,
        "v_ed_kn": 10.0,
        "v_rd_max_kn": 100.0,
        "t_ed_equivalent_kn": 10.0,
        "t_rd_max_equivalent_kn": 100.0,
        "parameter_basis": conformance.STANDARD_BASIS,
        "custom_methodology": "",
        "approval_reference": "",
    }


def _minimum_record(factor):
    return {
        "component": "Web",
        "act_mm2": 100_000.0,
        "k_c": 0.4,
        "k": factor,
        "fct_eff_mpa": 3.0,
        "sigma_s_mpa": 300.0,
        "as_provided_mm2": 500.0,
        "restrained_shrinkage": False,
        "parameter_basis": conformance.STANDARD_BASIS,
        "custom_methodology": "",
        "approval_reference": "",
    }


@pytest.mark.parametrize(
    ("key", "record"),
    [
        (
            bridge_inputs.BOX_WALL_TABLE_KEY,
            _box_wall_record(bridge.BOX_WALL_COT_THETA_MIN),
        ),
        (
            bridge_inputs.BOX_WALL_TABLE_KEY,
            _box_wall_record(bridge.BOX_WALL_COT_THETA_MAX),
        ),
        (
            bridge_inputs.MINIMUM_TABLE_KEY,
            _minimum_record(bridge.MINIMUM_CRACK_K_MIN),
        ),
        (
            bridge_inputs.MINIMUM_TABLE_KEY,
            _minimum_record(bridge.MINIMUM_CRACK_K_MAX),
        ),
    ],
)
def test_normative_bridge_parameter_bounds_round_trip(key, record):
    assert bridge_inputs.table_errors([record], key) == []
    assert bridge_inputs.table_records([record], key) == [record]


@pytest.mark.parametrize(
    ("key", "record"),
    [
        (
            bridge_inputs.BOX_WALL_TABLE_KEY,
            _box_wall_record(
                math.nextafter(bridge.BOX_WALL_COT_THETA_MIN, 0.0)
            ),
        ),
        (
            bridge_inputs.BOX_WALL_TABLE_KEY,
            _box_wall_record(
                math.nextafter(
                    bridge.BOX_WALL_COT_THETA_MAX,
                    math.inf,
                )
            ),
        ),
        (
            bridge_inputs.BOX_WALL_TABLE_KEY,
            _box_wall_record(10.0),
        ),
        (
            bridge_inputs.MINIMUM_TABLE_KEY,
            _minimum_record(
                math.nextafter(bridge.MINIMUM_CRACK_K_MIN, 0.0)
            ),
        ),
        (
            bridge_inputs.MINIMUM_TABLE_KEY,
            _minimum_record(
                math.nextafter(bridge.MINIMUM_CRACK_K_MAX, math.inf)
            ),
        ),
        (
            bridge_inputs.MINIMUM_TABLE_KEY,
            _minimum_record(0.01),
        ),
    ],
)
def test_positive_bridge_parameter_deviation_is_retained_with_warning(
    key,
    record,
):
    errors = bridge_inputs.table_errors([record], key)
    stored = bridge_inputs.table_records([record], key)
    warnings = bridge_inputs.conformance_warnings({key: stored})

    assert errors == []
    assert stored[0] == record
    assert warnings
    assert any("does not conform" in warning for warning in warnings)


@pytest.mark.parametrize(
    ("key", "record", "expected"),
    [
        (
            bridge_inputs.BOX_WALL_TABLE_KEY,
            _box_wall_record(True),
            "cot_theta must be finite",
        ),
        (
            bridge_inputs.BOX_WALL_TABLE_KEY,
            _box_wall_record(float("nan")),
            "cot_theta must be finite",
        ),
        (
            bridge_inputs.MINIMUM_TABLE_KEY,
            _minimum_record(True),
            "k must be finite",
        ),
        (
            bridge_inputs.MINIMUM_TABLE_KEY,
            _minimum_record(float("inf")),
            "k must be finite",
        ),
        (
            bridge_inputs.MINIMUM_TABLE_KEY,
            _minimum_record(0.0),
            "k must be greater than zero",
        ),
    ],
)
def test_numerically_invalid_bridge_parameter_is_rejected_at_table_boundary(
    key,
    record,
    expected,
):
    errors = bridge_inputs.table_errors([record], key)

    assert any(expected in error for error in errors)
    with pytest.raises(ValueError, match=expected):
        bridge_inputs.table_records([record], key)


@pytest.mark.parametrize(
    ("key", "record"),
    [
        (bridge_inputs.BOX_WALL_TABLE_KEY, _box_wall_record(10.0)),
        (bridge_inputs.MINIMUM_TABLE_KEY, _minimum_record(0.01)),
    ],
)
def test_approved_custom_bridge_parameter_round_trips_to_solver_adapter(
    key,
    record,
):
    record.update({
        "parameter_basis": conformance.CUSTOM_BASIS,
        "custom_methodology": "Project bridge analysis method",
        "approval_reference": "DB-BRIDGE-02 / checker B",
    })
    table = bridge_inputs.table_from_records([record], key)

    assert bridge_inputs.table_errors(table, key) == []
    warnings = bridge_inputs.conformance_warnings({key: table})
    assert any("approved custom input" in warning for warning in warnings)
    if key == bridge_inputs.BOX_WALL_TABLE_KEY:
        adapted = bridge_inputs.box_walls(table)[0]
        assert adapted.cot_theta == 10.0
    else:
        adapted = bridge_inputs.minimum_components(table)[0]
        assert adapted.k == 0.01
    assert adapted.parameter_basis == conformance.CUSTOM_BASIS
    assert adapted.custom_methodology == "Project bridge analysis method"
    assert adapted.approval_reference == "DB-BRIDGE-02 / checker B"


def test_coverage_normalisation_restores_missing_rows_as_not_established():
    frame = bridge_inputs.normalise_table(
        [{
            "check_id": "concrete_fatigue",
            "applicability": bridge.REQUIRED,
            "source": "DB-FAT",
            "notes": "",
        }],
        bridge_inputs.COVERAGE_TABLE_KEY,
    )

    decisions = {
        item.check_id: item
        for item in bridge_inputs.decisions(frame)
    }

    assert decisions["concrete_fatigue"].applicability == bridge.REQUIRED
    assert (
        decisions["sls_crack"].applicability
        == bridge.NOT_ESTABLISHED
    )


@pytest.mark.parametrize(
    "records",
    [
        [
            {
                "check_id": "sls_stress",
                "applicability": bridge.REQUIRED,
                "source": "DB-1",
                "notes": "",
            },
            {
                "check_id": "sls_stress",
                "applicability": bridge.NOT_APPLICABLE,
                "source": "DB-2",
                "notes": "",
            },
        ],
        [{
            "check_id": "made_up_bridge_check",
            "applicability": bridge.NOT_APPLICABLE,
            "source": "DB-X",
            "notes": "",
        }],
        [{
            "check_id": "sls_stress",
            "applicability": bridge.REQUIRED,
            "source": True,
            "notes": "",
        }],
    ],
)
def test_coverage_boundary_retains_malformed_row_findings(records):
    frame = bridge_inputs.normalise_table(
        records,
        bridge_inputs.COVERAGE_TABLE_KEY,
    )

    errors = bridge_inputs.table_errors(
        frame,
        bridge_inputs.COVERAGE_TABLE_KEY,
    )

    assert errors
    with pytest.raises(ValueError):
        bridge_inputs.table_records(
            frame,
            bridge_inputs.COVERAGE_TABLE_KEY,
        )


def test_text_boolean_is_not_coerced_to_bridge_evidence_boolean():
    errors = bridge_inputs.table_errors(
        [{
            "component": "Web",
            "act_mm2": 100_000.0,
            "k_c": 0.4,
            "k": 1.0,
            "fct_eff_mpa": 2.9,
            "sigma_s_mpa": 300.0,
            "as_provided_mm2": 500.0,
            "restrained_shrinkage": "true",
        }],
        bridge_inputs.MINIMUM_TABLE_KEY,
    )

    assert any("must be Boolean" in error for error in errors)
