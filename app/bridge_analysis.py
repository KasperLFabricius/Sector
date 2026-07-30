"""Application adapter for independent numerical bridge calculations."""

from __future__ import annotations

from collections.abc import Mapping

import bridge_inputs
from sector import bridge


def run(inp: Mapping) -> dict:
    """Run configured bridge kernels without a generic coverage aggregate."""
    standard = str(
        inp.get("bridge_standard") or bridge.COMPONENT_METHODS
    ).strip()
    if standard not in bridge.METHODS:
        raise ValueError(f"unknown selected bridge standard: {standard}")
    tables = {
        key: inp.get(key)
        for key in bridge_inputs.TABLE_KEYS
    }
    calculations = bridge_inputs.calculate(tables, standard=standard)
    return {
        "selected_standard": standard,
        "scope": (
            "Independent numerical calculations only; generic bridge-code "
            "coverage is not calculated."
        ),
        "calculations": calculations,
    }
