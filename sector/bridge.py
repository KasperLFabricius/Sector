"""Independent numerical kernels useful for bridge calculations.

The methods in this module are direct user choices. They do not form a bridge
coverage matrix and do not establish Eurocode, national-annex, owner or
project-basis compliance.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Final, Iterable, Literal, TypeAlias, TypedDict


BridgeMethod: TypeAlias = Literal[
    "Independent component calculations",
    "DS/EN 1992-2:2005 + AC:2008",
    "DS/EN 1992-2 DK NA:2015",
]
COMPONENT_METHODS: Final[BridgeMethod] = "Independent component calculations"
EN1992_2_BASE: Final[BridgeMethod] = "DS/EN 1992-2:2005 + AC:2008"
EN1992_2_DK_NA: Final[BridgeMethod] = "DS/EN 1992-2 DK NA:2015"
METHODS: Final[tuple[BridgeMethod, ...]] = (
    COMPONENT_METHODS,
    EN1992_2_BASE,
    EN1992_2_DK_NA,
)

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

CalculationStatus: TypeAlias = Literal["PASS", "FAIL"]
BridgeFailureCode: TypeAlias = Literal["INVALID_INPUT", "NON_FINITE_RESULT"]


class BrittleMethodRow(TypedDict):
    region_id: str
    m_rep_knm: float
    z_s_m: float
    f_yk_mpa: float
    as_required_mm2: float
    as_provided_mm2: float
    utilisation: float
    status: CalculationStatus


class BrittleMethodResult(TypedDict):
    method: str
    equation: str
    source: str
    selected_standard: BridgeMethod
    warning: str
    rows: list[BrittleMethodRow]


class BoxWallRow(TypedDict):
    wall_id: str
    cot_theta: float
    v_ed_kn: float
    v_rd_max_kn: float
    t_ed_equivalent_kn: float
    t_rd_max_equivalent_kn: float
    utilisation: float
    status: CalculationStatus


class BoxWallResult(TypedDict):
    method: str
    equation: str
    source: str
    rows: list[BoxWallRow]
    warnings: list[str]


class MinimumCrackRow(TypedDict):
    component: str
    act_mm2: float
    k_c: float
    k: float
    fct_eff_mpa: float
    sigma_s_mpa: float
    as_provided_mm2: float
    restrained_shrinkage: bool
    fct_eff_used_mpa: float
    as_required_mm2: float
    utilisation: float
    status: CalculationStatus


class MinimumCrackResult(TypedDict):
    method: str
    equation: str
    source: str
    rows: list[MinimumCrackRow]


class BridgeCalculations(TypedDict, total=False):
    brittle_method_b: BrittleMethodResult
    box_walls: BoxWallResult
    minimum_crack_reinforcement: MinimumCrackResult


class BridgeCalculationError(ValueError):
    """Expected bridge-boundary failure with a stable causal identity."""

    def __init__(self, code: BridgeFailureCode, field: str, message: str) -> None:
        self.code = code
        self.field = field
        self.message = message
        super().__init__(message)


def _real(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or isinstance(value, str):
        raise BridgeCalculationError(
            "INVALID_INPUT",
            label,
            f"{label} must be a real number",
        )
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise BridgeCalculationError(
            "INVALID_INPUT",
            label,
            f"{label} must be a real number",
        ) from exc
    if not math.isfinite(number):
        raise BridgeCalculationError(
            "INVALID_INPUT",
            label,
            f"{label} must be finite",
        )
    if positive and number <= 0.0:
        raise BridgeCalculationError(
            "INVALID_INPUT",
            label,
            f"{label} must be greater than zero",
        )
    return number


def _finite_result(value: float, label: str, *, positive: bool = False) -> float:
    if not math.isfinite(value) or (positive and value <= 0.0):
        raise BridgeCalculationError(
            "NON_FINITE_RESULT",
            label,
            f"{label} could not be represented as a finite result",
        )
    return value


def _divide(
    numerator: float,
    denominator: float,
    label: str,
    *,
    positive: bool = False,
) -> float:
    if not math.isfinite(denominator) or denominator == 0.0:
        raise BridgeCalculationError(
            "NON_FINITE_RESULT",
            label,
            f"{label} could not be represented as a finite result",
        )
    return _finite_result(numerator / denominator, label, positive=positive)


def parse_method(value: object) -> BridgeMethod:
    """Return one retained bridge method or raise a typed boundary failure."""
    selected = str(value or COMPONENT_METHODS).strip()
    if selected not in METHODS:
        raise BridgeCalculationError(
            "INVALID_INPUT",
            "bridge_standard",
            f"unknown selected bridge standard: {selected}",
        )
    return selected


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


def brittle_method_warning(selected_standard: BridgeMethod) -> str:
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
    numerator = _finite_result(1000.0 * moment, "As,min", positive=True)
    denominator = _finite_result(lever * strength, "As,min", positive=True)
    return _divide(numerator, denominator, "As,min", positive=True)


def calculate_brittle_method_b(
    regions: Iterable[PrestressBrittleRegion],
    *,
    selected_standard: BridgeMethod = COMPONENT_METHODS,
) -> BrittleMethodResult:
    """Calculate Method B for each declared tensile region."""
    rows: list[BrittleMethodRow] = []
    seen: set[str] = set()
    for index, region in enumerate(regions, start=1):
        region_id = str(region.region_id or "").strip()
        if not region_id:
            raise BridgeCalculationError(
                "INVALID_INPUT",
                "region_id",
                f"row {index}: tensile-region ID is required",
            )
        folded = region_id.casefold()
        if folded in seen:
            raise BridgeCalculationError(
                "INVALID_INPUT",
                "region_id",
                f"{region_id}: duplicate tensile-region ID",
            )
        seen.add(folded)
        moment = _real(region.m_rep_knm, f"{region_id}: Mrep", positive=True)
        lever = _real(region.z_s_m, f"{region_id}: zs", positive=True)
        strength = _real(region.f_yk_mpa, f"{region_id}: fyk", positive=True)
        required = minimum_brittle_reinforcement_area(
            moment,
            lever,
            strength,
        )
        provided = _real(
            region.as_provided_mm2,
            f"{region_id}: As,provided",
            positive=True,
        )
        utilisation = _divide(
            required,
            provided,
            f"{region_id}: utilisation",
            positive=True,
        )
        rows.append({
            "region_id": region_id,
            "m_rep_knm": moment,
            "z_s_m": lever,
            "f_yk_mpa": strength,
            "as_required_mm2": required,
            "as_provided_mm2": provided,
            "utilisation": utilisation,
            "status": "PASS" if utilisation <= 1.0 + _TOL else "FAIL",
        })
    if not rows:
        raise BridgeCalculationError(
            "INVALID_INPUT",
            "brittle_method_b",
            "Method B requires at least one tensile-region row",
        )
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
    shear_ratio = _divide(v_ed, v_rd, "wall VEd/VRd,max")
    torsion_ratio = _divide(
        t_ed,
        t_rd,
        "wall torsion-equivalent TEd/TRd,max",
    )
    return _finite_result(
        shear_ratio + torsion_ratio,
        "wall shear-plus-torsion utilisation",
    )


def calculate_box_walls(walls: Iterable[BoxWall]) -> BoxWallResult:
    """Calculate each box wall independently at the supplied common angle."""
    rows: list[BoxWallRow] = []
    seen: set[str] = set()
    cots: list[float] = []
    warnings: list[str] = []
    for index, wall in enumerate(walls, start=1):
        wall_id = str(wall.wall_id or "").strip()
        if not wall_id:
            raise BridgeCalculationError(
                "INVALID_INPUT",
                "wall_id",
                f"row {index}: wall ID is required",
            )
        folded = wall_id.casefold()
        if folded in seen:
            raise BridgeCalculationError(
                "INVALID_INPUT",
                "wall_id",
                f"{wall_id}: duplicate wall ID",
            )
        seen.add(folded)
        cot = _real(wall.cot_theta, f"{wall_id}: cot(theta)", positive=True)
        v_ed = _real(wall.v_ed_kn, f"{wall_id}: VEd")
        v_rd = _real(wall.v_rd_max_kn, f"{wall_id}: VRd,max", positive=True)
        t_ed = _real(
            wall.t_ed_equivalent_kn,
            f"{wall_id}: torsion-equivalent action",
        )
        t_rd = _real(
            wall.t_rd_max_equivalent_kn,
            f"{wall_id}: torsion-equivalent resistance",
            positive=True,
        )
        utilisation = box_wall_interaction(
            v_ed,
            v_rd,
            t_ed,
            t_rd,
        )
        cots.append(cot)
        rows.append({
            "wall_id": wall_id,
            "cot_theta": cot,
            "v_ed_kn": v_ed,
            "v_rd_max_kn": v_rd,
            "t_ed_equivalent_kn": t_ed,
            "t_rd_max_equivalent_kn": t_rd,
            "utilisation": utilisation,
            "status": "PASS" if utilisation <= 1.0 + _TOL else "FAIL",
        })
    if not rows:
        raise BridgeCalculationError(
            "INVALID_INPUT",
            "box_walls",
            "box-wall calculation requires at least one wall",
        )
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
        raise BridgeCalculationError(
            "INVALID_INPUT",
            "restrained_shrinkage",
            "restrained_shrinkage must be Boolean",
        )
    fct_used = max(fct, 2.9) if restrained_shrinkage else fct
    numerator = _finite_result(
        kc * factor * fct_used * act,
        "As,min",
        positive=True,
    )
    return _divide(numerator, sigma, "As,min", positive=True), fct_used


def calculate_minimum_crack_reinforcement(
    components: Iterable[MinimumCrackComponent],
) -> MinimumCrackResult:
    """Calculate independent web/flange minimum reinforcement checks."""
    rows: list[MinimumCrackRow] = []
    seen: set[str] = set()
    for index, item in enumerate(components, start=1):
        component = str(item.component or "").strip().casefold()
        if component not in {"web", "flange"}:
            raise BridgeCalculationError(
                "INVALID_INPUT",
                "component",
                f"row {index}: component must be Web or Flange",
            )
        if component in seen:
            raise BridgeCalculationError(
                "INVALID_INPUT",
                "component",
                f"{component}: duplicate component row",
            )
        seen.add(component)
        act = _real(item.act_mm2, f"{component}: Act", positive=True)
        kc = _real(item.k_c, f"{component}: kc", positive=True)
        factor = _real(item.k, f"{component}: k", positive=True)
        fct = _real(item.fct_eff_mpa, f"{component}: fct,eff", positive=True)
        sigma = _real(item.sigma_s_mpa, f"{component}: sigma_s", positive=True)
        required, fct_used = minimum_crack_reinforcement_area(
            act,
            kc,
            factor,
            fct,
            sigma,
            restrained_shrinkage=item.restrained_shrinkage,
        )
        provided = _real(
            item.as_provided_mm2,
            f"{component}: As,provided",
            positive=True,
        )
        utilisation = _divide(
            required,
            provided,
            f"{component}: utilisation",
            positive=True,
        )
        rows.append({
            "component": component,
            "act_mm2": act,
            "k_c": kc,
            "k": factor,
            "fct_eff_mpa": fct,
            "sigma_s_mpa": sigma,
            "as_provided_mm2": provided,
            "restrained_shrinkage": item.restrained_shrinkage,
            "fct_eff_used_mpa": fct_used,
            "as_required_mm2": required,
            "utilisation": utilisation,
            "status": "PASS" if utilisation <= 1.0 + _TOL else "FAIL",
        })
    if not rows:
        raise BridgeCalculationError(
            "INVALID_INPUT",
            "minimum_crack_reinforcement",
            "minimum crack reinforcement requires a web or flange component",
        )
    return {
        "method": "Separate web/flange minimum crack reinforcement",
        "equation": MINIMUM_CRACK_EQUATION,
        "source": MINIMUM_CRACK_SOURCE,
        "rows": rows,
    }
