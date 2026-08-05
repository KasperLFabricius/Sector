"""Application adapter for independent numerical bridge calculations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypeAlias, TypedDict

import bridge_inputs
from sector import bridge


BridgeFamily: TypeAlias = Literal[
    "bridge_standard",
    "brittle_method_b",
    "box_walls",
    "minimum_crack_reinforcement",
]


class BridgeFailure(TypedDict):
    state: Literal["INVALID"]
    family: BridgeFamily
    code: bridge.BridgeFailureCode
    field: str
    message: str
    cause_type: str


class BridgePayload(TypedDict):
    selected_standard: str
    scope: str
    calculations: bridge.BridgeCalculations
    failures: tuple[BridgeFailure, ...]


_SCOPE = (
    "Independent numerical calculations only; generic bridge-code "
    "coverage is not calculated."
)


def _failure(
    family: BridgeFamily,
    exc: bridge.BridgeCalculationError,
) -> BridgeFailure:
    cause = exc.__cause__
    return {
        "state": "INVALID",
        "family": family,
        "code": exc.code,
        "field": exc.field,
        "message": exc.message,
        "cause_type": type(cause if cause is not None else exc).__name__,
    }


def run(inp: Mapping[str, object]) -> BridgePayload:
    """Run configured bridge kernels without a generic coverage aggregate."""
    selected = str(
        inp.get("bridge_standard") or bridge.COMPONENT_METHODS
    ).strip()
    calculations: bridge.BridgeCalculations = {}
    failures: list[BridgeFailure] = []
    try:
        standard = bridge.parse_method(selected)
    except bridge.BridgeCalculationError as exc:
        failures.append(_failure("bridge_standard", exc))
        standard = None

    if standard is not None:
        try:
            brittle = bridge_inputs.calculate_brittle(
                inp.get(bridge_inputs.BRITTLE_TABLE_KEY),
                standard=standard,
            )
        except bridge.BridgeCalculationError as exc:
            failures.append(_failure("brittle_method_b", exc))
        else:
            if brittle is not None:
                calculations["brittle_method_b"] = brittle

    try:
        walls = bridge_inputs.calculate_box_walls(
            inp.get(bridge_inputs.BOX_WALL_TABLE_KEY)
        )
    except bridge.BridgeCalculationError as exc:
        failures.append(_failure("box_walls", exc))
    else:
        if walls is not None:
            calculations["box_walls"] = walls

    try:
        minimum = bridge_inputs.calculate_minimum_crack(
            inp.get(bridge_inputs.MINIMUM_CRACK_TABLE_KEY)
        )
    except bridge.BridgeCalculationError as exc:
        failures.append(_failure("minimum_crack_reinforcement", exc))
    else:
        if minimum is not None:
            calculations["minimum_crack_reinforcement"] = minimum

    return {
        "selected_standard": selected,
        "scope": _SCOPE,
        "calculations": calculations,
        "failures": tuple(failures),
    }


def run_or_invalid(inp: Mapping[str, object]) -> BridgePayload:
    """Return typed INVALID evidence while unexpected faults still propagate."""
    return run(inp)
