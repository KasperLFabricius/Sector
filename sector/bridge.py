"""Decommission marker for the retired component-mapped bridge kernels.

Sector project schema 24 has no semantic region, wall, web or flange mapping.
This strict-owned module remains importable only to make that removal explicit;
it exposes no engineering calculator, method selector or result type.
"""

from __future__ import annotations

from typing import Final


DECOMMISSIONED: Final[bool] = True
DECOMMISSIONED_IN_PROJECT_SCHEMA: Final[int] = 24
RETIRED_PROJECT_KEYS: Final[tuple[str, ...]] = (
    "bridge_standard",
    "bridge_brittle_base",
    "bridge_box_walls_base",
    "bridge_minimum_crack_base",
)
DECOMMISSION_REASON: Final[str] = (
    "Bridge component mapping is outside the current calculation scope."
)
