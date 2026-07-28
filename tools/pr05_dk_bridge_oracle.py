"""Independent scalar/decision oracle for PR-05 Danish bridge choices.

The oracle deliberately imports no Sector production module.  Its route tables
and scalar relationships are transcribed independently from the controlled
local DS/EN 1992-2 DK NA:2015 decision map.
"""

from __future__ import annotations

import json
import math
from pathlib import Path


FREQUENT = "Frequent"
QUASI_PERMANENT = "Quasi-permanent"


def crack_route(asset_class: str, member_class: str, environment: str):
    """Return independent `(kind, combination, limit)` acceptance rows."""

    if asset_class not in {"road", "footbridge", "railway"}:
        raise ValueError("unmapped bridge class")
    if environment not in {"aggressive", "extra_aggressive"}:
        raise ValueError("unmapped Danish bridge environment")
    if member_class == "nonprestressed":
        limit = 0.30 if environment == "aggressive" else 0.20
        return (("width", FREQUENT, limit),)
    if member_class != "prestressed":
        raise ValueError("unmapped Danish member class")
    if asset_class == "railway":
        limit = 0.10
    else:
        limit = 0.20 if environment == "aggressive" else 0.10
    return (
        ("width", FREQUENT, limit),
        ("decompression", QUASI_PERMANENT, None),
    )


def nominal_cover_requirement_mm(
    environment: str,
    cover_category: str,
    *,
    railway_collision_risk: bool = False,
) -> float:
    """Return independent `cmin,dur + Delta cdev` route in millimetres."""

    if environment not in {"aggressive", "extra_aggressive"}:
        raise ValueError("unmapped Danish bridge environment")
    if cover_category not in {
        "nonprestressed",
        "pretensioned",
        "posttension_duct",
    }:
        raise ValueError("unmapped cover category")
    extra = environment == "extra_aggressive"
    if cover_category == "posttension_duct":
        cmin_dur = 60.0 if extra else 50.0
    else:
        cmin_dur = 50.0 if extra else 40.0
    required = cmin_dur + 5.0
    if railway_collision_risk:
        if cover_category == "nonprestressed":
            raise ValueError("collision route requires prestressing")
        required = max(required, 75.0)
    return required


def fctm_mpa(fck_mpa: float) -> float:
    """2004-family mean tensile strength for the frozen `fck <= 50` case."""

    fck = float(fck_mpa)
    if not math.isfinite(fck) or fck <= 0.0 or fck > 50.0:
        raise ValueError("oracle case requires 0 < fck <= 50 MPa")
    return 0.30 * fck ** (2.0 / 3.0)


def torsional_cracking_knm(
    *,
    fck_mpa: float,
    gamma_ct: float,
    alpha_ct: float,
    ak_m2: float,
    tef_mm: float,
) -> float:
    """Independent `2 Ak tef alpha_ct fctk,0.05 / gamma_ct` result."""

    values = (fck_mpa, gamma_ct, alpha_ct, ak_m2, tef_mm)
    if any(isinstance(value, bool) for value in values):
        raise ValueError("Boolean values are not engineering coefficients")
    fctk_005 = 0.70 * fctm_mpa(fck_mpa)
    return (
        2.0
        * float(ak_m2)
        * (float(tef_mm) / 1000.0)
        * float(alpha_ct)
        * fctk_005
        / float(gamma_ct)
        * 1000.0
    )


def authority_mapping(manager: str, asset_class: str) -> str:
    """Return the independent mapped/qualified authority effect."""

    mapped = {
        "road_directorate": {"road", "footbridge"},
        "local_road": {"road", "footbridge"},
        "banedanmark": {"railway"},
        "regional_rail": {"railway"},
    }
    if manager == "other" or asset_class == "other":
        return "REVIEW_ONLY"
    return (
        "MAPPED"
        if asset_class in mapped.get(manager, set())
        else "CONFLICT_REVIEW"
    )


def evaluate_fixture(path: str | Path) -> dict:
    """Evaluate the frozen JSON fixture with only independent oracle code."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "crack_cases": {
            case["id"]: crack_route(
                case["asset_class"],
                case["member_class"],
                case["environment"],
            )
            for case in data["crack_cases"]
        },
        "cover_cases": {
            case["id"]: nominal_cover_requirement_mm(
                case["environment"],
                case["cover_category"],
                railway_collision_risk=case.get(
                    "railway_collision_risk", False
                ),
            )
            for case in data["cover_cases"]
        },
        "torsion_cases": {
            case["id"]: torsional_cracking_knm(**case["inputs"])
            for case in data["torsion_cases"]
        },
        "authority_cases": {
            case["id"]: authority_mapping(
                case["manager"], case["asset_class"]
            )
            for case in data["authority_cases"]
        },
    }


if __name__ == "__main__":
    fixture = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "pr05_dk_bridge_decisions.json"
    )
    print(json.dumps(evaluate_fixture(fixture), indent=2))
