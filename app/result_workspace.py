"""Read-only result selection using the existing governing result records."""

from __future__ import annotations

import hashlib
import json

FILTERS = ("All checks", "Needs attention", "Calculated outputs")
_CLEAR = frozenset({
    "PASS", "WITHIN USER-SPECIFIED LIMIT",
    "PROVIDED AREA AT LEAST CALCULATED REQUIREMENT", "CALCULATED",
    "NOT APPLICABLE", "NOT REQUESTED",
})


def identity(row):
    return tuple(str(row.get(key) or "") for key in ("overview_key", "family", "case", "view", "check"))


def is_output(row):
    return (str(row.get("overview_key") or "").startswith("elastic_stress:")
            or row.get("overview_key") == "cracking_threshold"
            or row.get("status") in {"CALCULATED", "CALCULATED - NO LIMIT COMPARISON"})


def filter_rows(rows, choice):
    if choice == "Needs attention":
        return [row for row in rows if row.get("status") not in _CLEAR]
    if choice == "Calculated outputs":
        return [row for row in rows if is_output(row)]
    return list(rows)


def reconcile_selection(rows, previous):
    """Retain the same record after sorting, filtering or a fresh calculation."""
    matches = [index for index, row in enumerate(rows) if identity(row) == previous]
    return matches[0] if len(matches) == 1 else (0 if rows else None)


def table_key(rows, choice):
    """A changed row inventory must never reuse positional browser selections."""
    encoded = json.dumps([choice, [identity(row) for row in rows]], ensure_ascii=True)
    return "overview_rows_" + hashlib.sha256(encoded.encode()).hexdigest()[:20]


def input_destination(row):
    """Map an authored result family to a visible related input group."""
    view = row.get("view")
    if view in {"Shear", "Torsion", "M-V-T Combined"}:
        return "settings", "Shear / torsion / M-V-T", {
            "Shear": "Shear", "Torsion": "Torsion", "M-V-T Combined": "Combined M-V-T"
        }[view]
    if view == "Detailing":
        return "settings", "Detailing", None
    if view == "Fatigue Results":
        return "settings", "Fatigue", None
    if "crack" in str(row.get("overview_key") or ""):
        return "settings", "Crack width", None
    return "actions", None, None
