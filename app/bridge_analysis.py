"""Application-boundary marker for retired component-mapped bridge workflows.

The former adapter has no callable run boundary in project schema 24. Keeping
this strict-owned path as an inert marker preserves the accepted type-quality
ratchet without retaining an executable compatibility API.
"""

from __future__ import annotations

from typing import Final


DECOMMISSIONED: Final[bool] = True
DECOMMISSIONED_IN_PROJECT_SCHEMA: Final[int] = 24
RETIRED_ADAPTER_API: Final[tuple[str, ...]] = (
    "run",
    "bridge_brittle_base",
    "bridge_box_walls_base",
    "bridge_minimum_crack_base",
)
DECOMMISSION_REASON: Final[str] = (
    "Sector no longer accepts or dispatches semantic bridge component tables."
)
