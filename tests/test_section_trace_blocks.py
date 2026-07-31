from __future__ import annotations

import dataclasses

import pytest

from sector.section import Section
from sector.section_trace_blocks import context_axes, context_id, section_trace_blocks


@pytest.fixture
def block_input():
    section = Section.from_polygon(
        [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        [(0.06, 0.05, 500.0), (0.24, 0.55, 500.0)],
        tendons_xy_area_mm2=[(0.15, 0.08, 400.0)],
    )
    return {
        "section": section,
        "P_pl": 0.0,
        "Mx_pl": 10.0,
        "My_pl": 20.0,
    }


def test_geometry_and_actions_are_exact_immutable_blocks(block_input):
    blocks = section_trace_blocks(block_input)
    assert dict(blocks.plastic_actions.values) == {
        "P_pl": 0.0,
        "Mx_pl": 10.0,
        "My_pl": 20.0,
    }
    assert len(blocks.geometry.rings) == 1
    assert len(blocks.geometry.bars) == 2
    assert len(blocks.geometry.tendons) == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        blocks.plastic_actions.values = ()


@pytest.mark.parametrize("malformed", [True, "10", float("inf"), float("nan")])
def test_actions_reject_non_numeric_boolean_and_nonfinite_values(block_input, malformed):
    with pytest.raises(ValueError, match="actions"):
        section_trace_blocks({**block_input, "P_pl": malformed})


def test_context_identity_and_axes_are_exact_and_order_independent():
    first = {"case": "A/B", "stage": 2}
    second = {"stage": 2, "case": "A/B"}
    assert context_id(first) == context_id(second)
    assert context_axes(first, axis="x") == context_axes(second, axis="x")
    assert context_axes(first, axis="x") != context_axes(first, axis="y")
