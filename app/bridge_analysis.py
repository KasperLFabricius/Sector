"""Application adapter for independent numerical bridge calculations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypedDict

import bridge_inputs
from sector import bridge


class BridgeFailure(TypedDict):
    family: str
    table_key: str
    state: Literal["INVALID", "UNSUPPORTED"]
    code: Literal[
        "INVALID_INPUT",
        "NUMERICAL_FAILURE",
        "UNSUPPORTED_STANDARD",
    ]
    message: str


class BridgePayload(TypedDict):
    selected_standard: str
    scope: str
    calculations: dict[str, bridge.BridgeResult]
    failures: tuple[BridgeFailure, ...]


_SCOPE = (
    "Independent numerical calculations only; generic bridge-code coverage "
    "is not calculated."
)


def _failure(
    *,
    family: str,
    table_key: str,
    state: Literal["INVALID", "UNSUPPORTED"],
    code: Literal[
        "INVALID_INPUT",
        "NUMERICAL_FAILURE",
        "UNSUPPORTED_STANDARD",
    ],
    message: str,
) -> BridgeFailure:
    return {
        "family": family,
        "table_key": table_key,
        "state": state,
        "code": code,
        "message": message,
    }


def run(inp: Mapping[str, object]) -> BridgePayload:
    """Run independent kernels with narrow, family-local typed failures."""
    raw_standard = inp.get("bridge_standard")
    standard = (
        bridge.COMPONENT_METHODS
        if raw_standard is None
        else str(raw_standard).strip()
    )
    if not standard:
        standard = bridge.COMPONENT_METHODS
    if standard not in bridge.METHODS:
        return {
            "selected_standard": standard,
            "scope": _SCOPE,
            "calculations": {},
            "failures": (_failure(
                family="selected_standard",
                table_key="bridge_standard",
                state="UNSUPPORTED",
                code="UNSUPPORTED_STANDARD",
                message=f"unknown selected bridge standard: {standard}",
            ),),
        }

    calculations: dict[str, bridge.BridgeResult] = {}
    failures: list[BridgeFailure] = []
    for key in bridge_inputs.TABLE_KEYS:
        family = bridge_inputs.CALCULATION_KEYS[key]
        try:
            family_result = bridge_inputs.calculate_family(
                inp.get(key),
                key,
                standard=standard,
            )
        except bridge.BridgeInputError as exc:
            failures.append(_failure(
                family=family,
                table_key=key,
                state="INVALID",
                code="INVALID_INPUT",
                message=str(exc),
            ))
            continue
        except bridge.BridgeNumericalError as exc:
            failures.append(_failure(
                family=family,
                table_key=key,
                state="INVALID",
                code="NUMERICAL_FAILURE",
                message=str(exc),
            ))
            continue
        if family_result is not None:
            result_family, result = family_result
            calculations[result_family] = result

    return {
        "selected_standard": standard,
        "scope": _SCOPE,
        "calculations": calculations,
        "failures": tuple(failures),
    }
