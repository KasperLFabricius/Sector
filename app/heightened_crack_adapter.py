"""Bind dual DK heightened control to retained ordinary crack evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real


@dataclass(frozen=True, slots=True)
class HeightenedReinforcementContribution:
    """One retained mild-bar contribution used by the heightened calculation."""

    element_id: str
    material_id: str
    material_name: str | None
    area_mm2: float
    diameter_mm: float
    diameter_source: str
    reinforcement_modulus_mpa: float


@dataclass(frozen=True, slots=True)
class DerivedHeightenedReinforcement:
    """Auto-derived Formula 7.100 NA reinforcement operands and provenance."""

    reference_case_id: str
    ordinary_crack_branch: str
    bar_diameter_mm: float
    diameter_source: str
    diameter_governing_element_ids: tuple[str, ...]
    reinforcement_modulus_mpa: float
    modulus_governing_material_ids: tuple[str, ...]
    provided_reinforcement_area_mm2: float
    contributions: tuple[HeightenedReinforcementContribution, ...]


_CRACK_RESULT_KEYS = {
    "Long-term": "crack",
    "Short-term": "crack_short",
    "Long-term (fine)": "crack",
    "Short-term (fine)": "crack_short",
    "Long-term (coarse)": "crack_coarse",
    "Short-term (coarse)": "crack_short_coarse",
}


def _positive_finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a positive finite real number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{label} must be a positive finite real number")
    return number


def crack_enabled_case_names(records: Sequence[Mapping]) -> tuple[str, ...]:
    """Return crack-enabled Elastic case names in their canonical table order."""

    return tuple(
        str(record.get("name") or "").strip()
        for record in records
        if record.get("calculate_crack_width") is True
        and str(record.get("name") or "").strip()
    )


def resolve_reference_case_name(
    records: Sequence[Mapping],
    selected: object,
) -> str:
    """Apply the exact one-case-auto / many-cases-explicit reference policy."""

    names = crack_enabled_case_names(records)
    if not names:
        raise ValueError(
            "Heightened crack control requires at least one crack-enabled "
            "Elastic case"
        )
    if len(names) == 1:
        return names[0]
    if not isinstance(selected, str) or selected not in names:
        raise ValueError(
            "Select one crack-enabled Elastic case as the heightened reference"
        )
    return selected


def _selected_crack_result(elastic: Mapping) -> tuple[str, Mapping]:
    output = elastic.get("crack_output")
    if not isinstance(output, Mapping):
        raise ValueError(
            "The heightened reference case has no retained ordinary crack output"
        )
    candidates = []
    for tie_order, duration in enumerate(("long_term", "short_term")):
        assessment = output.get(duration)
        if not isinstance(assessment, Mapping):
            continue
        value = assessment.get("value")
        if isinstance(value, bool):
            continue
        try:
            width = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        branch = str(assessment.get("case") or "").strip()
        if math.isfinite(width) and width >= 0.0 and branch:
            candidates.append((width, -tie_order, branch, assessment))
    if not candidates:
        reasons = [
            str(assessment.get("reason") or "").strip()
            for duration in ("long_term", "short_term")
            if isinstance((assessment := output.get(duration)), Mapping)
            and str(assessment.get("reason") or "").strip()
        ]
        suffix = f": {'; '.join(dict.fromkeys(reasons))}" if reasons else ""
        raise ValueError(
            "The heightened reference case has no governing calculated ordinary "
            f"crack branch{suffix}"
        )
    _width, _order, branch, _assessment = max(candidates)
    result_key = _CRACK_RESULT_KEYS.get(branch)
    if result_key is None:
        reason = str(_assessment.get("reason") or "").strip()
        suffix = f": {reason}" if reason else ""
        raise ValueError(
            "The heightened reference case has no governing calculated ordinary "
            f"crack branch{suffix}"
        )
    crack = elastic.get(result_key)
    if not isinstance(crack, Mapping):
        raise ValueError(
            "The heightened reference case is missing the retained ordinary "
            f"crack evidence for {branch}"
        )
    return branch, crack


def derive_heightened_reinforcement(
    case_entry: Mapping,
    *,
    bar_diameter_override_mm: object,
) -> DerivedHeightenedReinforcement:
    """Derive shared heightened operands only from one retained case result.

    Every mild-bar candidate must close exactly to the ordinary calculation's
    retained ``As,eff`` and to a typed Elastic element row.  Any missing identity,
    material, modulus, diameter or area evidence blocks the calculation.
    """

    reference_case_id = str(case_entry.get("name") or "").strip()
    if not reference_case_id:
        raise ValueError("The heightened reference case has no stable name")
    case_results = case_entry.get("results")
    elastic = case_results.get("elastic") if isinstance(case_results, Mapping) else None
    if not isinstance(elastic, Mapping):
        raise ValueError(
            "The heightened reference case has no retained Elastic result"
        )
    branch, crack = _selected_crack_result(elastic)
    effective_reinforcement = crack.get("effective_reinforcement")
    if not isinstance(effective_reinforcement, Sequence) or isinstance(
        effective_reinforcement, (str, bytes)
    ):
        raise ValueError(
            "The heightened reference case has no retained effective-"
            "reinforcement evidence"
        )
    mild_contributions = [
        retained
        for retained in effective_reinforcement
        if isinstance(retained, Mapping)
        and retained.get("element_type") == "Bar"
        and retained.get("reinforcement_type") == "mild"
        and retained.get("in_effective_area") is True
    ]
    if not mild_contributions:
        raise ValueError(
            "The heightened reference crack evidence has no contributing mild bars"
        )

    elements = elastic.get("elements")
    if not isinstance(elements, Sequence) or isinstance(elements, (str, bytes)):
        raise ValueError(
            "The heightened reference case has no retained Elastic element evidence"
        )
    element_rows: dict[str, Mapping] = {}
    for row in elements:
        if not isinstance(row, Mapping) or row.get("element_type") != "Bar":
            continue
        element_id = str(row.get("element_id") or "").strip()
        if not element_id or element_id in element_rows:
            raise ValueError(
                "The heightened reference case has ambiguous mild-bar identities"
            )
        element_rows[element_id] = row

    contributions = []
    seen: set[str] = set()
    for retained in mild_contributions:
        element_id = str(retained.get("element_id") or "").strip()
        if not element_id or element_id in seen:
            raise ValueError(
                "The heightened reference reinforcement evidence has ambiguous "
                "mild-bar identities"
            )
        seen.add(element_id)
        element = element_rows.get(element_id)
        if element is None:
            raise ValueError(
                f"The retained reinforcement element {element_id!r} has no matching "
                "Elastic element evidence"
            )
        contribution_area = _positive_finite(
            retained.get("effective_area_contribution_mm2"),
            f"Retained effective-area contribution for {element_id}",
        )
        element_area = _positive_finite(
            element.get("area_mm2"),
            f"Elastic element area for {element_id}",
        )
        if not math.isclose(
            contribution_area,
            element_area,
            rel_tol=1.0e-9,
            abs_tol=1.0e-6,
        ):
            raise ValueError(
                "Retained effective-area and Elastic element areas disagree for "
                f"{element_id}"
            )
        material_id = str(element.get("material_id") or "").strip()
        if not material_id:
            raise ValueError(
                f"The contributing mild bar {element_id} has no material identity"
            )
        diameter = _positive_finite(
            retained.get("diameter_mm"),
            f"Retained ordinary crack diameter for {element_id}",
        )
        diameter_source = str(retained.get("diameter_source") or "").strip()
        if not diameter_source:
            raise ValueError(
                f"The contributing mild bar {element_id} has no diameter source"
            )
        modulus = _positive_finite(
            retained.get("modulus_mpa"),
            f"Retained reinforcement modulus for {element_id}",
        )
        elastic_modulus = _positive_finite(
            element.get("modulus_mpa"),
            f"Elastic element modulus for {element_id}",
        )
        if not math.isclose(
            modulus,
            elastic_modulus,
            rel_tol=1.0e-12,
            abs_tol=1.0e-9,
        ):
            raise ValueError(
                f"Retained crack and Elastic moduli disagree for {element_id}"
            )
        material_name = str(element.get("material_name") or "").strip() or None
        contributions.append(
            HeightenedReinforcementContribution(
                element_id=element_id,
                material_id=material_id,
                material_name=material_name,
                area_mm2=contribution_area,
                diameter_mm=diameter,
                diameter_source=diameter_source,
                reinforcement_modulus_mpa=modulus,
            )
        )

    provided_area = sum(item.area_mm2 for item in contributions)
    retained_as_eff = _positive_finite(
        crack.get("as_eff"),
        "Retained ordinary effective mild-reinforcement area",
    ) * 1.0e6
    if not math.isclose(
        provided_area,
        retained_as_eff,
        rel_tol=1.0e-9,
        abs_tol=1.0e-6,
    ):
        raise ValueError(
            "The retained ordinary effective-reinforcement elements do not close to the "
            "effective mild-reinforcement area"
        )

    override = 0.0
    if not isinstance(bar_diameter_override_mm, bool) and isinstance(
        bar_diameter_override_mm, Real
    ):
        override = float(bar_diameter_override_mm)
    if not math.isfinite(override) or override < 0.0:
        raise ValueError(
            "The ordinary crack diameter override must be finite and non-negative"
        )
    if override > 0.0:
        diameter = override
        diameter_source = "ordinary crack diameter override sls_phi"
        diameter_ids = tuple(item.element_id for item in contributions)
        if any(
            not math.isclose(
                item.diameter_mm,
                override,
                rel_tol=1.0e-9,
                abs_tol=1.0e-9,
            )
            for item in contributions
        ):
            raise ValueError(
                "The retained ordinary crack diameters do not match the active "
                "diameter override"
            )
    else:
        diameter = max(item.diameter_mm for item in contributions)
        diameter_source = "largest contributing mild bar in ordinary crack evidence"
        diameter_ids = tuple(
            item.element_id
            for item in contributions
            if math.isclose(
                item.diameter_mm,
                diameter,
                rel_tol=1.0e-12,
                abs_tol=1.0e-12,
            )
        )
    modulus = min(item.reinforcement_modulus_mpa for item in contributions)
    modulus_material_ids = tuple(dict.fromkeys(
        item.material_id
        for item in contributions
        if math.isclose(
            item.reinforcement_modulus_mpa,
            modulus,
            rel_tol=1.0e-12,
            abs_tol=1.0e-9,
        )
    ))
    return DerivedHeightenedReinforcement(
        reference_case_id=reference_case_id,
        ordinary_crack_branch=branch,
        bar_diameter_mm=diameter,
        diameter_source=diameter_source,
        diameter_governing_element_ids=diameter_ids,
        reinforcement_modulus_mpa=modulus,
        modulus_governing_material_ids=modulus_material_ids,
        provided_reinforcement_area_mm2=provided_area,
        contributions=tuple(contributions),
    )
