"""Decommission contract for component-mapped bridge calculations."""

from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import bridge_analysis  # noqa: E402
import project_io  # noqa: E402
from sector import bridge  # noqa: E402


RETIRED_KEYS = (
    "bridge_standard",
    "bridge_brittle_base",
    "bridge_box_walls_base",
    "bridge_minimum_crack_base",
)


def test_strict_owned_bridge_modules_are_inert_schema24_markers():
    assert bridge.DECOMMISSIONED is True
    assert bridge.DECOMMISSIONED_IN_PROJECT_SCHEMA == 24
    assert bridge.RETIRED_PROJECT_KEYS == RETIRED_KEYS
    assert bridge_analysis.DECOMMISSIONED is True
    assert bridge_analysis.DECOMMISSIONED_IN_PROJECT_SCHEMA == 24
    assert "run" in bridge_analysis.RETIRED_ADAPTER_API


def test_retired_bridge_engineering_api_is_not_available():
    for name in (
        "METHODS",
        "COMPONENT_METHODS",
        "EN1992_2_BASE",
        "EN1992_2_DK_NA",
        "BridgeInputError",
        "BridgeNumericalError",
        "PrestressBrittleRegion",
        "BoxWall",
        "MinimumCrackComponent",
        "calculate_brittle_method_b",
        "calculate_box_walls",
        "calculate_minimum_crack_reinforcement",
        "minimum_brittle_reinforcement_area",
        "box_wall_interaction",
        "minimum_crack_reinforcement_area",
    ):
        assert not hasattr(bridge, name), name
    assert not hasattr(bridge_analysis, "run")


def test_current_schema_has_no_retired_bridge_input_identity():
    assert project_io.VERSION == 27
    assert not set(RETIRED_KEYS).intersection(project_io.PROJECT_TABLE_KEYS)
    assert not set(RETIRED_KEYS).intersection(project_io.SCALAR_KEYS)
    assert not (ROOT / "app" / "bridge_inputs.py").exists()
