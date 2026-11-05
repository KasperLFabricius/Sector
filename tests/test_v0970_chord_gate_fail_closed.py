"""The a_l = d chord publication gate fails closed on evidence that it cannot read."""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))

import result_presentation  # noqa: E402


@pytest.mark.parametrize("inp, direction", [(None, {}), ({}, None)])
def test_assessment_of_a_payload_that_is_not_a_mapping_is_unavailable(inp, direction):
    assessment = result_presentation.concrete_route_chord_publication_assessment(
        inp, direction
    )
    assert assessment["required"] is None
    assert assessment["valid"] is False
    assert assessment["chord"] is None
    assert assessment["reason"]


def test_no_chord_is_required_on_an_empty_route():
    assessment = result_presentation.concrete_route_chord_publication_assessment({}, {})
    assert assessment["required"] is False
    assert assessment["valid"] is True
    assert assessment["chord"] is None


def test_retained_chord_on_a_route_that_needs_none_is_unavailable():
    assessment = result_presentation.concrete_route_chord_publication_assessment(
        {}, {"concrete_chord": {"valid": True}}
    )
    assert assessment["required"] is False
    assert assessment["valid"] is False
    assert assessment["chord"] is None


def test_current_chord_operands_without_a_current_action_are_unavailable():
    assert result_presentation._current_concrete_route_chord({}, {}) is None


def test_summary_row_of_unavailable_evidence_is_not_assessed():
    row = result_presentation._concrete_route_chord_summary_row(None, {}, "")
    assert row["check"] == "Shear tension chord (a_l = d)"
    assert row["status"] == "NOT ASSESSED"
    assert row["util"] is None
