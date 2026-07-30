"""Independent numerical kernels useful for bridge calculations.

The methods in this module are direct user choices. They do not form a bridge
coverage matrix and do not establish Eurocode, national-annex, owner or
project-basis compliance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable


COMPONENT_METHODS = "Independent component calculations"
EN1992_2_BASE = "DS/EN 1992-2:2005 + AC:2008"
EN1992_2_DK_NA = "DS/EN 1992-2 DK NA:2015"
METHODS = (COMPONENT_METHODS, EN1992_2_BASE, EN1992_2_DK_NA)

BRITTLE_METHOD_B = "Method B - minimum reinforcement"
BRITTLE_METHOD_B_EQUATION = "As,min = Mrep / (zs fyk)"
BRITTLE_METHOD_B_SOURCE = "DS/EN 1992-2:2005 6.1(109)-(110)"

BOX_WALL_EQUATION = "VEd/VRd,max + TEd,wall/TRd,max,wall <= 1.0"
BOX_WALL_SOURCE = (
    "DS/EN 1992-2:2005 6.3.2(101)-(104), including AC:2008 corrections"
)
BOX_WALL_COT_THETA_DEFAULT_RANGE = (1.0, 2.5)

MINIMUM_CRACK_EQUATION = "As,min = kc k fct,eff Act / sigma_s"
MINIMUM_CRACK_SOURCE = "DS/EN 1992-2:2005 7.3.2(102)-(105)"

_TOL = 1.0e-9


def _real(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError(f"{label} must be a real number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a real number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    if positive and number <= 0.0:
        raise ValueError(f"{label} must be greater than zero")
    return number


@dataclass(frozen=True)
class PrestressBrittleRegion:
    region_id: str
    m_rep_knm: Any
    z_s_m: Any
    f_yk_mpa: Any
    as_provided_mm2: Any


@dataclass(frozen=True)
class BoxWall:
    wall_id: str
    cot_theta: Any
    v_ed_kn: Any
    v_rd_max_kn: Any
    t_ed_equivalent_kn: Any
    t_rd_max_equivalent_kn: Any


@dataclass(frozen=True)
class MinimumCrackComponent:
    component: str
    act_mm2: Any
    k_c: Any
    k: Any
    fct_eff_mpa: Any
    sigma_s_mpa: Any
    as_provided_mm2: Any
    restrained_shrinkage: bool = False


def brittle_method_warning(selected_standard: str) -> str:
    """Return a scope warning without suppressing Method-B calculation."""
    if str(selected_standard or "").strip() == EN1992_2_DK_NA:
        return (
            "The selected Danish bridge standard expects a different "
            "brittle-failure method. Method B remains available as an explicit "
            "numerical calculation and does not establish compliance."
        )
    return ""


def minimum_brittle_reinforcement_area(
    m_rep_knm: Any,
    z_s_m: Any,
    f_yk_mpa: Any,
) -> float:
    """Return Method-B ``As,min`` in square millimetres."""
    moment = _real(m_rep_knm, "Mrep", positive=True)
    lever = _real(z_s_m, "zs", positive=True)
    strength = _real(f_yk_mpa, "fyk", positive=True)
    return 1000.0 * moment / (lever * strength)


def calculate_brittle_method_b(
    regions: Iterable[PrestressBrittleRegion],
    *,
    selected_standard: str = COMPONENT_METHODS,
) -> dict:
    """Calculate Method B for each declared tensile region."""
    rows = []
    seen: set[str] = set()
    for index, region in enumerate(regions, start=1):
        region_id = str(region.region_id or "").strip()
        if not region_id:
            raise ValueError(f"row {index}: tensile-region ID is required")
        folded = region_id.casefold()
        if folded in seen:
            raise ValueError(f"{region_id}: duplicate tensile-region ID")
        seen.add(folded)
        required = minimum_brittle_reinforcement_area(
            region.m_rep_knm,
            region.z_s_m,
            region.f_yk_mpa,
        )
        provided = _real(
            region.as_provided_mm2,
            f"{region_id}: As,provided",
            positive=True,
        )
        utilisation = required / provided
        rows.append({
            "region_id": region_id,
            "m_rep_knm": float(region.m_rep_knm),
            "z_s_m": float(region.z_s_m),
            "f_yk_mpa": float(region.f_yk_mpa),
            "as_required_mm2": required,
            "as_provided_mm2": provided,
            "utilisation": utilisation,
            "status": "PASS" if utilisation <= 1.0 + _TOL else "FAIL",
        })
    if not rows:
        raise ValueError("Method B requires at least one tensile-region row")
    return {
        "method": BRITTLE_METHOD_B,
        "equation": BRITTLE_METHOD_B_EQUATION,
        "source": BRITTLE_METHOD_B_SOURCE,
        "selected_standard": selected_standard,
        "warning": brittle_method_warning(selected_standard),
        "rows": rows,
    }


def box_wall_interaction(
    v_ed_kn: Any,
    v_rd_max_kn: Any,
    t_ed_equivalent_kn: Any,
    t_rd_max_equivalent_kn: Any,
) -> float:
    """Return the per-wall linear shear-plus-torsion utilisation."""
    v_ed = abs(_real(v_ed_kn, "wall VEd"))
    v_rd = _real(v_rd_max_kn, "wall VRd,max", positive=True)
    t_ed = abs(_real(t_ed_equivalent_kn, "wall torsion-equivalent action"))
    t_rd = _real(
        t_rd_max_equivalent_kn,
        "wall torsion-equivalent resistance",
        positive=True,
    )
    return v_ed / v_rd + t_ed / t_rd


def calculate_box_walls(walls: Iterable[BoxWall]) -> dict:
    """Calculate each box wall independently at the supplied common angle."""
    rows = []
    seen: set[str] = set()
    cots: list[float] = []
    warnings: list[str] = []
    for index, wall in enumerate(walls, start=1):
        wall_id = str(wall.wall_id or "").strip()
        if not wall_id:
            raise ValueError(f"row {index}: wall ID is required")
        folded = wall_id.casefold()
        if folded in seen:
            raise ValueError(f"{wall_id}: duplicate wall ID")
        seen.add(folded)
        cot = _real(wall.cot_theta, f"{wall_id}: cot(theta)", positive=True)
        utilisation = box_wall_interaction(
            wall.v_ed_kn,
            wall.v_rd_max_kn,
            wall.t_ed_equivalent_kn,
            wall.t_rd_max_equivalent_kn,
        )
        cots.append(cot)
        rows.append({
            **asdict(wall),
            "cot_theta": cot,
            "utilisation": utilisation,
            "status": "PASS" if utilisation <= 1.0 + _TOL else "FAIL",
        })
    if not rows:
        raise ValueError("box-wall calculation requires at least one wall")
    if not all(math.isclose(cot, cots[0], abs_tol=_TOL) for cot in cots[1:]):
        warnings.append(
            "Box-wall rows use different cot(theta) values; the cited method "
            "expects one common strut angle."
        )
    low, high = BOX_WALL_COT_THETA_DEFAULT_RANGE
    if any(cot < low or cot > high for cot in cots):
        warnings.append(
            "One or more supplied cot(theta) values are outside the selected "
            "method's default range 1.0 to 2.5; the actual values were retained."
        )
    return {
        "method": "Separate box-wall shear/torsion interaction",
        "equation": BOX_WALL_EQUATION,
        "source": BOX_WALL_SOURCE,
        "rows": rows,
        "warnings": warnings,
    }


def minimum_crack_reinforcement_area(
    act_mm2: Any,
    k_c: Any,
    k: Any,
    fct_eff_mpa: Any,
    sigma_s_mpa: Any,
    *,
    restrained_shrinkage: bool = False,
) -> tuple[float, float]:
    """Return ``(As,min, fct,eff used)`` for bridge Expression (7.1)."""
    act = _real(act_mm2, "Act", positive=True)
    kc = _real(k_c, "kc", positive=True)
    factor = _real(k, "k", positive=True)
    fct = _real(fct_eff_mpa, "fct,eff", positive=True)
    sigma = _real(sigma_s_mpa, "sigma_s", positive=True)
    if not isinstance(restrained_shrinkage, bool):
        raise ValueError("restrained_shrinkage must be Boolean")
    fct_used = max(fct, 2.9) if restrained_shrinkage else fct
    return kc * factor * fct_used * act / sigma, fct_used


def calculate_minimum_crack_reinforcement(
    components: Iterable[MinimumCrackComponent],
) -> dict:
    """Calculate independent web/flange minimum reinforcement checks."""
    rows = []
    seen: set[str] = set()
    for index, item in enumerate(components, start=1):
        component = str(item.component or "").strip().casefold()
        if component not in {"web", "flange"}:
            raise ValueError(f"row {index}: component must be Web or Flange")
        if component in seen:
            raise ValueError(f"{component}: duplicate component row")
        seen.add(component)
        required, fct_used = minimum_crack_reinforcement_area(
            item.act_mm2,
            item.k_c,
            item.k,
            item.fct_eff_mpa,
            item.sigma_s_mpa,
            restrained_shrinkage=item.restrained_shrinkage,
        )
        provided = _real(
            item.as_provided_mm2,
            f"{component}: As,provided",
            positive=True,
        )
        utilisation = required / provided
        rows.append({
            **asdict(item),
            "component": component,
            "fct_eff_used_mpa": fct_used,
            "as_required_mm2": required,
            "as_provided_mm2": provided,
            "utilisation": utilisation,
            "status": "PASS" if utilisation <= 1.0 + _TOL else "FAIL",
        })
    if not rows:
        raise ValueError(
            "minimum crack reinforcement requires a web or flange component"
        )
    return {
        "method": "Separate web/flange minimum crack reinforcement",
        "equation": MINIMUM_CRACK_EQUATION,
        "source": MINIMUM_CRACK_SOURCE,
        "rows": rows,
    }
