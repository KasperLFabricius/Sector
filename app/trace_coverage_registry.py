"""Selected-case PI-019 calculation-family registry.

This module derives trace identities from solver inputs and retained result
records only.  It never evaluates an engineering formula.  The generic
``sector.trace_registry`` invariant then matches those identities injectively
against the solver-adjacent trace builders.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sector import trace_builders
from sector.calculation_trace import TraceValidationError
from sector.trace_registry import (
    EXPLICIT_STATE,
    FINITE_RESULT,
    TraceFamilyExpectation,
    TraceMemberExpectation,
)


def _record_value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _is_finite_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class _StandardFamilyRule:
    required_documents: frozenset[str] = frozenset()
    forbidden_documents: frozenset[str] = frozenset()


_ALL_STANDARD_DOCUMENTS = frozenset(
    {
        trace_builders.DOC_2005,
        trace_builders.DOC_DKNA,
        trace_builders.DOC_2023,
        trace_builders.DOC_BRIDGE,
        trace_builders.DOC_BRIDGE_AC,
    }
)
_STANDARD_FAMILY_RULES = {
    "sector": _StandardFamilyRule(),
    "mixed-standard-project": _StandardFamilyRule(),
    "user-defined": _StandardFamilyRule(
        forbidden_documents=_ALL_STANDARD_DOCUMENTS
    ),
    "ec2-2005": _StandardFamilyRule(
        required_documents=frozenset({trace_builders.DOC_2005}),
        forbidden_documents=frozenset(
            {
                trace_builders.DOC_DKNA,
                trace_builders.DOC_2023,
                trace_builders.DOC_BRIDGE,
                trace_builders.DOC_BRIDGE_AC,
            }
        ),
    ),
    "ec2-2005-dkna": _StandardFamilyRule(
        required_documents=frozenset({trace_builders.DOC_DKNA}),
        forbidden_documents=frozenset(
            {
                trace_builders.DOC_2023,
                trace_builders.DOC_BRIDGE,
                trace_builders.DOC_BRIDGE_AC,
            }
        ),
    ),
    # An NA material preset is identified exactly by method_id. Constitutive
    # equations remain sourced to the base standard, so no NA citation is
    # invented solely to restate the preset name.
    "ec2-2005-section": _StandardFamilyRule(
        required_documents=frozenset({trace_builders.DOC_2005}),
        forbidden_documents=frozenset(
            {
                trace_builders.DOC_2023,
                trace_builders.DOC_BRIDGE,
                trace_builders.DOC_BRIDGE_AC,
            }
        ),
    ),
    "ec2-2023": _StandardFamilyRule(
        required_documents=frozenset({trace_builders.DOC_2023}),
        forbidden_documents=frozenset(
            {
                trace_builders.DOC_2005,
                trace_builders.DOC_DKNA,
                trace_builders.DOC_BRIDGE,
                trace_builders.DOC_BRIDGE_AC,
            }
        ),
    ),
    "en1992-2-2005": _StandardFamilyRule(
        required_documents=frozenset({trace_builders.DOC_BRIDGE}),
        forbidden_documents=frozenset(
            {
                trace_builders.DOC_DKNA,
                trace_builders.DOC_2023,
            }
        ),
    ),
}


def _public_context(
    context: Mapping[str, Any],
    **extra: Any,
) -> tuple[tuple[str, str], ...]:
    values = {**context, **extra}
    return tuple(
        (str(key), str(value))
        for key, value in sorted(values.items())
        if str(key) != "_case_identity"
    )


def _member(
    member_id: str,
    calculation_id: str,
    coverage_id: str,
    method_id: str,
    *,
    context: Mapping[str, Any],
    standard_based: bool,
    user_defined_method: bool = False,
    standard_family: str,
    result_state: str = FINITE_RESULT,
) -> TraceMemberExpectation:
    rule = _STANDARD_FAMILY_RULES[standard_family]
    return TraceMemberExpectation(
        member_id=member_id,
        calculation_id=trace_builders._slug(calculation_id),
        coverage_id=coverage_id,
        method_id=trace_builders._slug(method_id),
        context=_public_context(context),
        standard_based=standard_based,
        user_defined_method=user_defined_method,
        standard_family=standard_family,
        result_state=result_state,
        required_documents=rule.required_documents,
        forbidden_documents=rule.forbidden_documents,
    )


def _code_standard_family(code: Any) -> str:
    if code is None:
        return "user-defined"
    return "ec2-2023" if code.key == "EC2-2023" else "ec2-2005-section"


def _section_method(
    inp: Mapping[str, Any],
) -> tuple[str, bool, bool, str]:
    """Return the exact method identity used by the section trace builders."""

    code = trace_builders._preset_code(inp)
    bar_laws = trace_builders._material_sequence(
        inp,
        "bar_materials",
        inp.get("steel"),
    )
    tendon_laws = trace_builders._material_sequence(
        inp,
        "tendon_materials",
        inp.get("prestress"),
    )
    bar_presets = tuple(
        trace_builders._assigned_material_preset(
            inp,
            kind="bar",
            index=index,
        )
        if "bar_materials" in inp
        else trace_builders._capacity_steel_preset(inp)
        for index in range(len(bar_laws))
    )
    tendon_presets = tuple(
        trace_builders._assigned_material_preset(
            inp,
            kind="tendon",
            index=index,
        )
        if "tendon_materials" in inp
        else str(inp.get("prestress_preset") or "")
        for index in range(len(tendon_laws))
    )
    assigned_codes = tuple(
        trace_builders._code_from_preset(preset)
        for preset in (*bar_presets, *tendon_presets)
    )
    custom_assigned = any(item is None for item in assigned_codes)
    assigned_standard = any(item is not None for item in assigned_codes)
    standard_based = code is not None and not custom_assigned
    user_defined = code is None and not assigned_standard
    if standard_based:
        return code.key, True, False, _code_standard_family(code)
    if user_defined:
        return (
            "user-defined-material-section-solve",
            False,
            True,
            "user-defined",
        )
    return (
        "mixed-standard-project-material-section-solve",
        False,
        False,
        "mixed-standard-project",
    )


def _material_members(
    inp: Mapping[str, Any],
    _result: Mapping[str, Any],
    _context_value: Mapping[str, Any],
) -> tuple[TraceMemberExpectation, ...]:
    if inp.get("concrete") is None or inp.get("steel") is None:
        return ()
    context = {"family": "global", "case_id": "materials"}
    cid = trace_builders._context_id(context)
    concrete_code = trace_builders._preset_code(inp)
    steel_code = trace_builders._code_from_preset(
        trace_builders._capacity_steel_preset(inp)
    )
    return (
        _member(
            "material.concrete",
            f"material.{cid}.concrete",
            "CT-001",
            (
                concrete_code.key
                if concrete_code is not None
                else "user-defined-concrete"
            ),
            context=context,
            standard_based=concrete_code is not None,
            user_defined_method=concrete_code is None,
            standard_family=_code_standard_family(concrete_code),
        ),
        _member(
            "material.reinforcement",
            f"material.{cid}.steel",
            "CT-001",
            (
                steel_code.key
                if steel_code is not None
                else "user-defined-reinforcement"
            ),
            context=context,
            standard_based=steel_code is not None,
            user_defined_method=steel_code is None,
            standard_family=_code_standard_family(steel_code),
        ),
    )


def _plastic_members(
    inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[TraceMemberExpectation, ...]:
    plastic = result.get("plastic")
    if not isinstance(plastic, Mapping):
        return ()
    method, standard_based, user_defined, standard_family = _section_method(
        inp
    )
    cid = trace_builders._context_id(context)
    members = [
        _member(
            "plastic.capacity",
            f"plastic.{cid}.capacity",
            "CT-002",
            method,
            context=context,
            standard_based=standard_based,
            user_defined_method=user_defined,
            standard_family=standard_family,
        )
    ]
    if _is_finite_number(plastic.get("util")):
        members.append(
            _member(
                "plastic.radial-utilisation",
                f"plastic.{cid}.radial-utilisation",
                "CT-003",
                "sector-radial-envelope-intersection",
                context=context,
                standard_based=False,
                standard_family="sector",
            )
        )
    interaction = plastic.get("interaction")
    if isinstance(interaction, Mapping):
        for axis in ("x", "y"):
            branch = interaction.get(axis)
            if not isinstance(branch, Mapping):
                continue
            axial = list(branch.get("N") or ())
            moments = list(branch.get("M") or ())
            if not axial or len(axial) != len(moments):
                continue
            members.append(
                _member(
                    f"plastic.interaction.{axis}",
                    f"plastic.{cid}.interaction-{axis}",
                    "CT-004",
                    method,
                    context={**context, "axis": axis},
                    standard_based=standard_based,
                    user_defined_method=user_defined,
                    standard_family=standard_family,
                )
            )
    return tuple(members)


def _elastic_members(
    inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[TraceMemberExpectation, ...]:
    elastic = result.get("elastic")
    if not isinstance(elastic, Mapping):
        return ()
    cid = trace_builders._context_id(context)
    members = [
        _member(
            "elastic.section-equilibrium",
            f"elastic.{cid}.section-equilibrium",
            "CT-005",
            "sector-transformed-section-equilibrium",
            context=context,
            standard_based=False,
            standard_family="sector",
        )
    ]
    lambda_cr = elastic.get("lambda_cr")
    if lambda_cr is not None:
        threshold = elastic.get("cracking_threshold")
        fixed_prestress = (
            isinstance(threshold, Mapping)
            and threshold.get("method") == "fixed-prestress-decompression"
        )
        members.append(
            _member(
                "elastic.first-cracking",
                f"elastic.{cid}.cracking-factor",
                "CT-005",
                (
                    "sector-fixed-prestress-decompression"
                    if fixed_prestress
                    else "sector-linear-elastic-scaling"
                ),
                context=context,
                standard_based=False,
                standard_family="sector",
                result_state=(
                    FINITE_RESULT
                    if _is_finite_number(lambda_cr)
                    else EXPLICIT_STATE
                ),
            )
        )
    for key, label in (
        ("crack", "Long-term fine"),
        ("crack_short", "Short-term fine"),
        ("crack_coarse", "Long-term coarse"),
        ("crack_short_coarse", "Short-term coarse"),
    ):
        record = elastic.get(key)
        if not isinstance(record, Mapping):
            continue
        edition_2023 = str(record.get("edition") or "") == "2023"
        coarse = bool(record.get("coarse"))
        direct = bool(record.get("direct_tension"))
        dk = bool(inp.get("sls_dk_na")) and not edition_2023
        coverage_id = (
            "CT-008" if edition_2023 else "CT-007" if dk else "CT-006"
        )
        method_id = (
            "ec2-2023-direct-tension"
            if edition_2023 and direct
            else "ec2-2023-bending"
            if edition_2023
            else "ec2-2005-dkna-coarse"
            if dk and coarse
            else "ec2-2005-dkna-fine"
            if dk
            else "ec2-2005"
        )
        members.append(
            _member(
                f"crack.{key}",
                f"crack.{cid}.{trace_builders._slug(label)}",
                coverage_id,
                method_id,
                context={**context, "crack_case": label},
                standard_based=True,
                standard_family=(
                    "ec2-2023"
                    if edition_2023
                    else "ec2-2005-dkna"
                    if dk
                    else "ec2-2005"
                ),
            )
        )
    return tuple(members)


def _shear_records(
    payload: Mapping[str, Any],
) -> list[tuple[dict[str, str], Mapping[str, Any]]]:
    """Mirror the solver result's retained direction/face structure."""

    directions = payload.get("directions")
    if isinstance(directions, Mapping):
        records: list[tuple[dict[str, str], Mapping[str, Any]]] = []
        for component, direction in directions.items():
            if not isinstance(direction, Mapping):
                continue
            candidates = list(direction.get("face_candidates") or ())
            if candidates:
                for index, candidate in enumerate(candidates, start=1):
                    if not isinstance(candidate, Mapping):
                        continue
                    face_shear = candidate.get("shear")
                    if isinstance(face_shear, Mapping):
                        records.append(
                            (
                                {
                                    "component": str(component),
                                    "face": (
                                        "negative"
                                        if candidate.get("tension_low")
                                        else "positive"
                                    ),
                                    "candidate": str(index),
                                },
                                face_shear,
                            )
                        )
            else:
                records.append(({"component": str(component)}, direction))
        return records
    candidates = list(payload.get("face_candidates") or ())
    if candidates:
        records = []
        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, Mapping):
                continue
            face_shear = candidate.get("shear")
            if isinstance(face_shear, Mapping):
                records.append(
                    (
                        {
                            "component": str(
                                payload.get("component") or ""
                            ),
                            "face": (
                                "negative"
                                if candidate.get("tension_low")
                                else "positive"
                            ),
                            "candidate": str(index),
                        },
                        face_shear,
                    )
                )
        return records
    return [({"component": str(payload.get("component") or "")}, payload)]


def _shear_members(
    _inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[TraceMemberExpectation, ...]:
    shear = result.get("shear")
    if not isinstance(shear, Mapping):
        return ()
    members = []
    for extra, record in _shear_records(shear):
        resistance = record.get("res")
        if not isinstance(resistance, Mapping) or not resistance.get("valid"):
            continue
        record_context = {**context, **extra}
        cid = trace_builders._context_id(record_context)
        is_2023 = bool(
            resistance.get("model") == "2023" or record.get("model_2023")
        )
        is_dk = (
            not is_2023
            and "DK" in str(record.get("method") or "").upper()
        )
        method = (
            "ec2-2023"
            if is_2023
            else "ec2-2005-dkna"
            if is_dk
            else "ec2-2005"
        )
        family = (
            "ec2-2023"
            if is_2023
            else "ec2-2005-dkna"
            if is_dk
            else "ec2-2005"
        )
        identity = ".".join(
            (
                extra.get("component", ""),
                extra.get("face", ""),
                extra.get("candidate", ""),
            )
        )
        members.append(
            _member(
                f"shear.without-links.{identity}",
                f"shear.{cid}.without-links",
                "CT-010" if is_2023 else "CT-009",
                method,
                context=record_context,
                standard_based=True,
                standard_family=family,
                result_state=(
                    FINITE_RESULT
                    if _is_finite_number(record.get("util"))
                    else EXPLICIT_STATE
                ),
            )
        )
        links = record.get("links")
        link_result = (
            links.get("res") if isinstance(links, Mapping) else None
        )
        if not isinstance(link_result, Mapping) or not link_result.get(
            "valid"
        ):
            continue
        links_2023 = bool(
            links.get("model_2023")
            or link_result.get("model") == "2023"
        )
        links_dk = (
            not links_2023
            and "DK" in str(record.get("method") or "").upper()
        )
        members.append(
            _member(
                f"shear.with-links.{identity}",
                f"shear.{cid}.with-links",
                "CT-012" if links_2023 else "CT-011",
                (
                    "ec2-2023"
                    if links_2023
                    else "ec2-2005-dkna"
                    if links_dk
                    else "ec2-2005"
                ),
                context=record_context,
                standard_based=True,
                standard_family=(
                    "ec2-2023"
                    if links_2023
                    else "ec2-2005-dkna"
                    if links_dk
                    else "ec2-2005"
                ),
                result_state=(
                    FINITE_RESULT
                    if _is_finite_number(links.get("util"))
                    else EXPLICIT_STATE
                ),
            )
        )
    return tuple(members)


def _torsion_members(
    _inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[TraceMemberExpectation, ...]:
    torsion = result.get("torsion")
    if not isinstance(torsion, Mapping) or not torsion.get("valid"):
        return ()
    cid = trace_builders._context_id(context)
    dk = "DK" in str(torsion.get("method") or "").upper()
    method = "ec2-2005-dkna" if dk else "ec2-2005"
    family = "ec2-2005-dkna" if dk else "ec2-2005"
    tubes = list(torsion.get("subtubes") or ())
    if not tubes and isinstance(torsion.get("primary"), Mapping):
        tubes = [torsion["primary"]]
    members = [
        _member(
            f"torsion.tube.{index}",
            f"torsion.{cid}.tube-{index}",
            "CT-013",
            method,
            context={**context, "tube": f"Tube {index}"},
            standard_based=True,
            standard_family=family,
        )
        for index, tube in enumerate(tubes, start=1)
        if isinstance(tube, Mapping) and tube.get("valid")
    ]
    screen = torsion.get("min_reinf")
    if isinstance(screen, Mapping) and screen.get("applicable"):
        members.append(
            _member(
                "torsion.minimum-screen",
                f"torsion.{cid}.minimum-screen",
                "CT-013",
                "ec2-2005-formula-6-31",
                context=context,
                standard_based=True,
                standard_family="ec2-2005",
            )
        )
    return tuple(members)


def _combined_payload_members(
    combined: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    shear_2023: bool,
) -> list[TraceMemberExpectation]:
    if combined.get("biaxial") and isinstance(
        combined.get("directions"), Mapping
    ):
        members = []
        for component, direction in combined["directions"].items():
            if isinstance(direction, Mapping):
                members.extend(
                    _combined_payload_members(
                        direction,
                        context={**context, "component": str(component)},
                        shear_2023=False,
                    )
                )
        return members
    if not combined.get("valid"):
        return []
    cid = trace_builders._context_id(context)
    members = []
    transverse = combined.get("transverse")
    if isinstance(transverse, Mapping) and transverse.get("valid"):
        members.append(
            _member(
                f"combined.shared-stirrups.{cid}",
                f"combined.{cid}.shared-stirrups",
                "CT-014",
                "ec2-shared-transverse-reinforcement",
                context=context,
                standard_based=True,
                standard_family="ec2-2005",
            )
        )
    candidates = list(combined.get("longitudinal_candidates") or ())
    if not candidates:
        candidates = [
            item
            for item in (
                combined.get("longitudinal"),
                combined.get("chord_off"),
            )
            if isinstance(item, Mapping)
        ]
    for index, chord in enumerate(candidates, start=1):
        if not isinstance(chord, Mapping) or not chord.get("valid", True):
            continue
        chord_2023 = (
            str(chord.get("longitudinal_shear_symbol") or "").upper()
            == "NVD"
            or shear_2023
        )
        members.append(
            _member(
                f"combined.chord.{cid}.{index}",
                f"combined.{cid}.chord-{index}",
                "CT-015",
                "ec2-longitudinal-chord",
                context={**context, "chord": index},
                standard_based=True,
                standard_family=(
                    "ec2-2023" if chord_2023 else "ec2-2005"
                ),
                result_state=(
                    FINITE_RESULT
                    if _is_finite_number(chord.get("util"))
                    else EXPLICIT_STATE
                ),
            )
        )
    if combined.get("dkna_sum") is not None:
        members.append(
            _member(
                f"combined.dkna-sum.{cid}",
                f"combined.{cid}.dkna-sum",
                "CT-016",
                "dkna-2024-6-3-2-6",
                context=context,
                standard_based=True,
                standard_family="ec2-2005-dkna",
                result_state=(
                    FINITE_RESULT
                    if all(
                        _is_finite_number(combined.get(key))
                        for key in ("r_m", "r_v", "r_t")
                    )
                    else EXPLICIT_STATE
                ),
            )
        )
    return members


def _combined_members(
    _inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[TraceMemberExpectation, ...]:
    members = []
    torsion = result.get("torsion")
    if (
        isinstance(torsion, Mapping)
        and isinstance(torsion.get("interaction"), Mapping)
        and torsion["interaction"].get("valid")
    ):
        cid = trace_builders._context_id(context)
        members.append(
            _member(
                "combined.crushing",
                f"combined.{cid}.crushing",
                "CT-014",
                "ec2-formula-6-29",
                context=context,
                standard_based=True,
                standard_family="ec2-2005",
            )
        )
    combined = result.get("combined")
    if isinstance(combined, Mapping):
        shear = result.get("shear")
        members.extend(
            _combined_payload_members(
                combined,
                context=context,
                shear_2023=bool(
                    isinstance(shear, Mapping)
                    and shear.get("model_2023")
                ),
            )
        )
    return tuple(members)


def _minimum_members(
    _inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[TraceMemberExpectation, ...]:
    minimum = result.get("minimum_reinforcement")
    if not isinstance(minimum, Mapping):
        return ()
    edition = str(minimum.get("edition") or "")
    is_2023 = "2023" in edition
    is_dk = not is_2023 and "DK" in edition.upper()
    cid = trace_builders._context_id(context)
    members = []
    for index, check in enumerate(minimum.get("checks") or (), start=1):
        if not isinstance(check, Mapping) or str(
            check.get("status") or ""
        ).upper() not in {"PASS", "FAIL"}:
            continue
        failure_state = (
            check.get("as_min_mm2") is None
            if not is_2023
            else check.get("axial_feasible") is False
            or not _is_finite_number(check.get("utilisation"))
        )
        check_context = {**context, "check": index}
        if not is_2023 and check.get("as_min_mm2") is None:
            check_context["status"] = check.get("status")
        members.append(
            _member(
                f"minimum-reinforcement.check.{index}",
                f"detailing.{cid}.minimum-longitudinal-{index}",
                "CT-018" if is_2023 else "CT-017",
                (
                    "ec2-2023-formula-12-1-or-12-2"
                    if is_2023
                    else "ec2-2005-dkna-formula-9-1n"
                    if is_dk
                    else "ec2-2005-formula-9-1n"
                ),
                context=check_context,
                standard_based=True,
                standard_family=(
                    "ec2-2023"
                    if is_2023
                    else "ec2-2005-dkna"
                    if is_dk
                    else "ec2-2005"
                ),
                result_state=(
                    EXPLICIT_STATE if failure_state else FINITE_RESULT
                ),
            )
        )
    if (
        str(minimum.get("status") or "").upper() in {"PASS", "FAIL"}
        and not members
    ):
        raise TraceValidationError(
            "minimum longitudinal reinforcement declares a completed "
            "result without a completed check"
        )
    return tuple(members)


def _transverse_members(
    _inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[TraceMemberExpectation, ...]:
    transverse = result.get("transverse_reinforcement")
    if not isinstance(transverse, Mapping):
        return ()
    is_2023 = "2023" in str(transverse.get("edition") or "")
    cid = trace_builders._context_id(context)
    members = []
    for index, check in enumerate(
        transverse.get("checks") or (),
        start=1,
    ):
        if not isinstance(check, Mapping) or str(
            check.get("status") or ""
        ).upper() not in {"PASS", "FAIL"}:
            continue
        members.append(
            _member(
                f"transverse-reinforcement.check.{index}",
                f"detailing.{cid}.transverse-{index}",
                "CT-019",
                (
                    "ec2-2023-transverse"
                    if is_2023
                    else "ec2-2005-transverse"
                ),
                context={
                    **context,
                    "check": index,
                    "kind": check.get("kind"),
                },
                standard_based=True,
                standard_family=(
                    "ec2-2023" if is_2023 else "ec2-2005"
                ),
                result_state=(
                    FINITE_RESULT
                    if _is_finite_number(check.get("utilisation"))
                    else EXPLICIT_STATE
                ),
            )
        )
    if (
        str(transverse.get("status") or "").upper() in {"PASS", "FAIL"}
        and not members
    ):
        raise TraceValidationError(
            "transverse detailing declares a completed result without a "
            "completed check"
        )
    return tuple(members)


def _clear_spacing_members(
    _inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[TraceMemberExpectation, ...]:
    spacing = result.get("clear_spacing")
    if not isinstance(spacing, Mapping):
        return ()
    is_2023 = "2023" in str(spacing.get("edition") or "")
    return tuple(
        _member(
            f"clear-spacing.pair.{index}",
            f"detailing.global.clear-spacing-{index}",
            "CT-020",
            (
                "ec2-2023-clear-spacing"
                if is_2023
                else "ec2-2005-clear-spacing"
            ),
            context={**context, "pair": index},
            standard_based=True,
            standard_family=(
                "ec2-2023" if is_2023 else "ec2-2005"
            ),
        )
        for index, pair in enumerate(spacing.get("pairs") or (), start=1)
        if isinstance(pair, Mapping)
    )


def _fatigue_members(
    _inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[TraceMemberExpectation, ...]:
    fatigue = result.get("fatigue")
    if not isinstance(fatigue, Mapping) or fatigue.get("errors"):
        return ()
    edition_2023 = "2023" in str(fatigue.get("edition") or "")
    custom_details = {
        str(record.get("id") or ""): bool(record.get("custom"))
        for record in fatigue.get("fatigue_detail_basis") or ()
        if isinstance(record, Mapping)
    }
    members = []
    for spectrum in fatigue.get("spectra") or ():
        spectrum_name = _record_value(spectrum, "spectrum_name", "")
        spectrum_id = trace_builders._identified_slug(spectrum_name)
        for record in _record_value(spectrum, "reinforcement", ()) or ():
            if not _record_value(record, "bins"):
                continue
            element = _record_value(record, "element_id", "")
            element_id = trace_builders._identified_slug(element)
            custom = custom_details.get(
                str(_record_value(record, "detail_id", "")),
                False,
            )
            members.append(
                _member(
                    f"fatigue.reinforcement.{spectrum_id}.{element_id}",
                    f"fatigue.{spectrum_id}.reinforcement.{element_id}",
                    "CT-021",
                    (
                        "user-defined-sn-detail"
                        if custom
                        else "ec2-2023-reinforcement-sn"
                        if edition_2023
                        else "ec2-2005-reinforcement-sn"
                    ),
                    context={
                        **context,
                        "spectrum": spectrum_name,
                        "element": element,
                    },
                    standard_based=not custom,
                    user_defined_method=custom,
                    standard_family=(
                        "user-defined"
                        if custom
                        else "ec2-2023"
                        if edition_2023
                        else "ec2-2005"
                    ),
                )
            )
        for record in _record_value(spectrum, "concrete", ()) or ():
            if not _record_value(record, "bins"):
                continue
            fibre = int(_record_value(record, "fibre_index", 0)) + 1
            method = str(
                _record_value(
                    record,
                    "method",
                    fatigue.get("concrete_method"),
                )
                or ""
            )
            equivalent = "equivalent" in method.casefold()
            custom = (
                "user-defined" in method.casefold()
                or "project" in method.casefold()
            )
            members.append(
                _member(
                    f"fatigue.concrete.{spectrum_id}.fibre-{fibre}",
                    f"fatigue.{spectrum_id}.concrete.fibre-{fibre}",
                    (
                        "CT-024"
                        if edition_2023
                        else "CT-022"
                        if equivalent
                        else "CT-023"
                    ),
                    (
                        "user-defined-concrete-miner"
                        if custom
                        else "ec2-2023-equivalent"
                        if edition_2023 and equivalent
                        else "ec2-2023-miner"
                        if edition_2023
                        else "ec2-2005-equivalent"
                        if equivalent
                        else "ec2-bridge-corrected-miner"
                    ),
                    context={
                        **context,
                        "spectrum": spectrum_name,
                        "fibre": fibre,
                    },
                    standard_based=not custom,
                    user_defined_method=custom,
                    standard_family=(
                        "user-defined"
                        if custom
                        else "ec2-2023"
                        if edition_2023
                        else "ec2-2005"
                        if equivalent
                        else "en1992-2-2005"
                    ),
                )
            )
    return tuple(members)


def _bridge_members(
    _inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[TraceMemberExpectation, ...]:
    bridge = result.get("bridge")
    if not isinstance(bridge, Mapping) or bridge.get("errors"):
        return ()
    payload = bridge.get("calculations")
    if not isinstance(payload, Mapping):
        return ()
    members = []
    for key, coverage_id, component_key, id_prefix, method_id in (
        (
            "brittle_method_b",
            "CT-025",
            "region_id",
            "method-b",
            "en1992-2-method-b",
        ),
        (
            "box_walls",
            "CT-026",
            "wall_id",
            "box-wall",
            "en1992-2-box-wall-interaction",
        ),
        (
            "minimum_crack_reinforcement",
            "CT-027",
            "component",
            "minimum-crack",
            "en1992-2-minimum-crack-reinforcement",
        ),
    ):
        family = payload.get(key)
        if not isinstance(family, Mapping):
            continue
        for row in family.get("rows") or ():
            if not isinstance(row, Mapping):
                continue
            component = _record_value(row, component_key, "")
            component_id = trace_builders._identified_slug(component)
            members.append(
                _member(
                    f"bridge.{key}.{component_id}",
                    f"bridge.global.{id_prefix}-{component_id}",
                    coverage_id,
                    method_id,
                    context={**context, "component": component},
                    standard_based=True,
                    standard_family="en1992-2-2005",
                )
            )
    return tuple(members)


@dataclass(frozen=True)
class FamilyRegistration:
    family_id: str
    label: str
    coverage_ids: frozenset[str]
    derive: Callable[
        [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
        tuple[TraceMemberExpectation, ...],
    ]


CASE_CALCULATION_FAMILY_REGISTRY = (
    FamilyRegistration(
        "plastic",
        "plastic calculation family",
        frozenset({"CT-002", "CT-003", "CT-004"}),
        _plastic_members,
    ),
    FamilyRegistration(
        "elastic",
        "elastic and crack-width calculation family",
        frozenset({"CT-005", "CT-006", "CT-007", "CT-008"}),
        _elastic_members,
    ),
    FamilyRegistration(
        "shear",
        "shear calculation family",
        frozenset({"CT-009", "CT-010", "CT-011", "CT-012"}),
        _shear_members,
    ),
    FamilyRegistration(
        "torsion",
        "torsion calculation family",
        frozenset({"CT-013"}),
        _torsion_members,
    ),
    FamilyRegistration(
        "combined",
        "combined shear-torsion calculation family",
        frozenset({"CT-014", "CT-015", "CT-016"}),
        _combined_members,
    ),
    FamilyRegistration(
        "minimum-reinforcement",
        "minimum longitudinal reinforcement calculation family",
        frozenset({"CT-017", "CT-018"}),
        _minimum_members,
    ),
    FamilyRegistration(
        "transverse-reinforcement",
        "transverse detailing calculation family",
        frozenset({"CT-019"}),
        _transverse_members,
    ),
)

GLOBAL_CALCULATION_FAMILY_REGISTRY = (
    FamilyRegistration(
        "materials",
        "material calculation family",
        frozenset({"CT-001"}),
        _material_members,
    ),
    FamilyRegistration(
        "clear-spacing",
        "clear-spacing calculation family",
        frozenset({"CT-020"}),
        _clear_spacing_members,
    ),
    FamilyRegistration(
        "fatigue",
        "fatigue calculation family",
        frozenset({"CT-021", "CT-022", "CT-023", "CT-024"}),
        _fatigue_members,
    ),
    FamilyRegistration(
        "bridge",
        "bridge direct calculation family",
        frozenset({"CT-025", "CT-026", "CT-027"}),
        _bridge_members,
    ),
)


def registered_families(
    registrations: Sequence[FamilyRegistration],
    *,
    inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[TraceFamilyExpectation, ...]:
    """Materialise immutable expectations for one actual selected scope."""

    return tuple(
        TraceFamilyExpectation(
            family_id=registration.family_id,
            label=registration.label,
            coverage_ids=registration.coverage_ids,
            members=registration.derive(inp, result, context),
        )
        for registration in registrations
    )
