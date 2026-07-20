"""Tests for headless SLS assessment and evidence construction."""

from __future__ import annotations

import pytest

from sector import sls


def test_upper_limit_assessment_has_explicit_non_pass_states():
    assert sls.upper_limit_assessment(12.0, 18.0)["status"] == "OK"
    assert sls.upper_limit_assessment(20.0, 18.0)["status"] == "EXCEEDED"
    assert sls.upper_limit_assessment(12.0, 0.0)["status"] == "NOT ASSESSED"
    assert sls.upper_limit_assessment(None, 18.0, applicable=False)["status"] == \
        "NOT APPLICABLE"
    assert sls.upper_limit_assessment(12.0, 18.0, valid=False)["status"] == "INVALID"
    assert sls.upper_limit_assessment(float("nan"), 18.0)["status"] == "INVALID"


def test_stress_assessments_separate_bars_and_tendons():
    checks = sls.stress_assessments(
        [350.0, 420.0],
        n_bars=1,
        max_concrete_compression=20.0,
        fck=30.0,
        fyk=500.0,
        fpk=1800.0,
        concrete_limit_pct=60.0,
        reinforcement_limit_pct=80.0,
        prestress_limit_pct=75.0,
        valid=True,
    )
    assert checks["concrete"]["limit"] == pytest.approx(18.0)
    assert checks["concrete"]["status"] == "EXCEEDED"
    assert checks["reinforcement"]["governing"] == "bar 1"
    assert checks["reinforcement"]["status"] == "OK"
    assert checks["prestress"]["governing"] == "tendon 1"
    assert checks["prestress"]["limit"] == pytest.approx(1350.0)


def test_element_rows_are_typed_and_include_geometry_strain():
    rows = sls.element_rows(
        [(0.1, -0.2, 314.0)],
        [(-0.1, 0.2, 150.0)],
        total=[200.0, 975.0],
        long=[150.0, 900.0],
        dif=[50.0, 75.0],
        rst1=[40.0, 60.0],
        es_mpa=200_000.0,
        ep_mpa=195_000.0,
    )
    assert [row["element_id"] for row in rows] == ["bar 1", "tendon 1"]
    assert rows[0]["x_mm"] == pytest.approx(100.0)
    assert rows[0]["area_mm2"] == pytest.approx(314.0)
    assert rows[0]["strain_permille"] == pytest.approx(1.0)
    assert rows[1]["strain_permille"] == pytest.approx(5.0)


def test_concrete_corner_rows_use_public_one_based_points():
    rows = sls.concrete_corner_rows(
        [(-0.1, -0.2), (0.1, -0.2), (0.1, 0.2), (-0.1, 0.2)],
        [],
        stress_plane=(-10_000.0, 0.0, 60_000.0),
        ec_mpa=30_000.0,
    )
    assert [row["point_no"] for row in rows] == [1, 2, 3, 4]
    assert rows[0]["stress_mpa"] < 0.0
    assert rows[2]["stress_mpa"] == 0.0
    assert rows[2]["strain_permille"] > 0.0


def test_crack_assessment_selects_largest_case():
    result = sls.crack_assessment(
        {
            "Long-term": {"wk": 0.22, "element_id": "bar 2"},
            "Short-term": {"wk": 0.31, "element_id": "tendon 1"},
        },
        limit_mm=0.30,
        valid=True,
    )
    assert result["status"] == "EXCEEDED"
    assert result["case"] == "Short-term"
    assert result["governing"] == "tendon 1"
    assert result["margin"] == pytest.approx(-0.01)
