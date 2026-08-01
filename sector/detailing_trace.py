"""Solver-owned unpublished CT-008 detailing trace (clear spacing + links)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import detailing
from .calculation_trace import (
    RESULT_FINITE, RESULT_POSITIVE_INFINITY, TraceBundle, TraceCalculation,
    TraceDependency, TraceResult, TraceStep, TraceValidationError,
    create_bundle, validate_bundle,
)
from .detailing_trace_contract import (
    BarIdentity, CHECK_ROW_KEYS, CLEAR_INVALID_KEYS, CLEAR_KEYS,
    CLEAR_MEMBER_ID, COVERAGE_ID, ClearShape, DetailingShape, DirectionShape,
    DUCTILITY_CLASSES, EDITIONS, LONG_2005_KEYS, LONG_2023_BENDING_KEYS,
    LONG_2023_HIGH_COMPRESSION_KEYS, LONG_2023_SCOPE_KEYS,
    LONG_ROW_FIELD_CANDIDATES, LONG_SLAB_CUT_KEYS, LONGITUDINAL_MEMBER_ID,
    LongShape, METHOD_ID, MINIMUM_RATIO_KEYS, PAIR_KEYS, ROW_2005_KEYS,
    ROW_2023_BENDING_KEYS, ROW_2023_TENSION_KEYS, RecordShape, RowShape,
    STATUS_CODES, TORSION_LIMIT_KEYS, TRANSVERSE_INVALID_KEYS,
    TRANSVERSE_KEYS, TRANSVERSE_MEMBER_ID, TransverseShape, TubeShape,
    bar_leaf_id, concrete_leaf_id, expected_clear_steps,
    expected_longitudinal_steps, expected_registry, expected_transverse_steps,
    long_field_step_id, record_identity_id, tube_reason_id,
)
from .section_trace_blocks import (
    GeometryBlock, _concrete_block as concrete_material_block,
    _materials as bar_material_blocks, context_axes, context_id,
)
from .torsion_trace import (
    _boolean, _compare, _mapping, _number, _retained_mapping, _sequence,
)
from .trace_registry import audit_trace_registry


_DRIFT = "authoritative CT-008 output inventory drifted"
_SLAB_CLAUSE = "No slab torsion-link detailing provision selected"
_SCREEN = "gross-web upper-bound screen"
_INFINITE_REASON = (
    "Retained utilisation is unbounded because no effective transverse "
    "reinforcement is provided where it is required."
)


@dataclass(frozen=True, slots=True)
class MemberEvidence:
    values: dict[str, Any]
    expected: Mapping[str, Any]


def _compare_value(actual: Any, expected: Any, label: str) -> None:
    if isinstance(expected, float) and math.isinf(expected):
        if type(actual) is not float or actual != expected:
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    _compare(actual, expected, label)


def _compare_text_list(actual: Any, expected: Sequence[str], label: str) -> None:
    items = _sequence(actual, label)
    if len(items) != len(expected):
        raise TraceValidationError(f"{label} cardinality differs")
    for index, (item, wanted) in enumerate(zip(items, expected)):
        _compare(item, wanted, f"{label}[{index}]")


def _finite(value: Any, label: str) -> float:
    return _number(value, label)


def _upstream_scalar(value: Any, label: str, *, allow_none: bool = True):
    if value is None:
        if allow_none:
            return None
        raise TraceValidationError(f"{label} must be a number")
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a number or absent")
    return float(value)


def _bindable(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def detailing_trace_applicability(inp: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the applicable CT-008 members without touching unrelated inputs."""

    members = []
    clear = _boolean(inp.get("clear_spacing_on", False), "clear_spacing_on")
    transverse = _boolean(
        inp.get("transverse_detailing_on", False), "transverse_detailing_on"
    )
    longitudinal = _boolean(
        inp.get("minimum_reinforcement_on", False), "minimum_reinforcement_on"
    )
    has_section = inp.get("section") is not None
    if clear and has_section:
        members.append(CLEAR_MEMBER_ID)
    if transverse and has_section:
        members.append(TRANSVERSE_MEMBER_ID)
    if longitudinal and has_section:
        members.append(LONGITUDINAL_MEMBER_ID)
    return tuple(members)


def _require_section(inp: Mapping[str, Any]) -> None:
    validator = getattr(inp.get("section"), "require_valid_geometry", None)
    if not callable(validator):
        raise TraceValidationError("CT-008 needs a retained Section")
    validator()


def _edition(inp: Mapping[str, Any]) -> str:
    edition = inp.get("detailing_edition")
    if edition not in EDITIONS:
        raise TraceValidationError("unknown detailing edition")
    return edition


def _records(inp: Mapping[str, Any], key: str) -> tuple[Mapping[str, Any], ...]:
    raw = inp.get(key)
    if raw is None:
        return ()
    return tuple(_mapping(item, f"{key}[{index}]")
                 for index, item in enumerate(_sequence(raw, key)))


# ---------------------------------------------------------------------------
# Clear-spacing member.
# ---------------------------------------------------------------------------

def _replay_clear(inp, context):
    _require_section(inp)
    edition = _edition(inp)
    d_upper = _number(inp.get("detailing_d_upper"), "detailing_d_upper",
                      nonnegative=True)
    include = _boolean(inp.get("detailing_include_tendons", False),
                       "detailing_include_tendons")
    records = (*_records(inp, "bar_elements"), *_records(inp, "tendon_elements"))
    shapes, geometry = [], []
    for record in records:
        kind = str(record.get("kind") or "bar")
        is_bar = kind == "bar"
        included = is_bar or include
        try:
            parsed = (float(record["x_mm"]), float(record["y_mm"]),
                      float(record["diameter_mm"]))
        except (KeyError, TypeError, ValueError):
            parsed = None
        ok = (parsed is not None
              and all(math.isfinite(value) for value in parsed)
              and parsed[2] > 0.0)
        shapes.append(RecordShape(is_bar, included, ok,
                                  element_id=str(record.get("id") or ""),
                                  kind=kind))
        geometry.append(parsed if ok else None)
    invalid = any(shape.included and not shape.geometry_ok for shape in shapes)
    chosen = [index for index, shape in enumerate(shapes) if shape.included]
    pairs = () if invalid else tuple(
        (chosen[a], chosen[b])
        for a in range(len(chosen)) for b in range(a + 1, len(chosen))
    )
    expected = detailing.clear_spacing(
        list(inp.get("bar_elements") or []) + list(inp.get("tendon_elements") or []),
        d_upper_mm=inp["detailing_d_upper"],
        edition=inp["detailing_edition"],
        include_tendons=inp.get("detailing_include_tendons", False),
    )
    keys = tuple(expected)
    if keys != (CLEAR_INVALID_KEYS if invalid else CLEAR_KEYS):
        raise TraceValidationError(_DRIFT)
    if invalid != (expected["status"] == "INVALID"):
        raise TraceValidationError(_DRIFT)
    if not invalid and len(expected["pairs"]) != len(pairs):
        raise TraceValidationError(_DRIFT)

    branch = "invalid" if invalid else ("paired" if pairs else "empty")
    shape = ClearShape(
        tuple(shapes), pairs, invalid, edition,
        f"ct-008-{context_id(context)}-clear-spacing",
        context_axes(context, clear_branch=branch, detailing_edition=edition),
    )
    values: dict[str, Any] = {
        "input-clear-spacing-enabled": 1.0,
        "input-d-upper": d_upper,
        "input-edition": float(EDITIONS.index(edition)),
        "input-include-tendons": float(include),
        "elements-vector": 1.0,
        "normalised-clear-spacing-inputs": 1.0,
    }
    for index, (record, parsed) in enumerate(zip(shapes, geometry)):
        prefix = f"element-{index:03d}"
        values[f"{prefix}-is-bar"] = float(record.is_bar)
        values[f"{prefix}-included"] = float(record.included)
        if record.included:
            values[record_identity_id(index, record.element_id,
                                      record.kind)] = 1.0
        if record.included and record.geometry_ok:
            values[f"{prefix}-x"], values[f"{prefix}-y"] = parsed[0], parsed[1]
            values[f"{prefix}-diameter"] = parsed[2]
    code = STATUS_CODES[expected["status"]]
    if invalid:
        values["invalid-geometry-state"] = float(len(expected["invalid_ids"]))
    elif not pairs:
        values["no-pairs-state"] = 1.0
    else:
        for (first, second), row in zip(pairs, expected["pairs"]):
            if tuple(row) != PAIR_KEYS:
                raise TraceValidationError(_DRIFT)
            pair = f"pair-{first:03d}-{second:03d}"
            values[f"{pair}-centre-distance"] = row["centre_distance_mm"]
            values[f"{pair}-clear"] = row["clear_mm"]
            values[f"{pair}-required"] = row["required_mm"]
            values[f"{pair}-margin"] = row["margin_mm"]
            values[f"{pair}-verdict"] = float(row["status"] == "PASS")
        governing = expected["governing"]
        index = next(i for i, row in enumerate(expected["pairs"])
                     if row is governing)
        values["governing-margin"] = governing["margin_mm"]
        values["governing-pair"] = float(index)
        values["clear-spacing-status"] = code
    values["ct-008-clear-spacing-result"] = code
    return shape, MemberEvidence(values, expected)


def _validate_pair(candidate, expected, label):
    candidate = _retained_mapping(candidate, PAIR_KEYS, (), label)
    for key in PAIR_KEYS:
        _compare_value(candidate[key], expected[key], f"{label}.{key}")


def _validate_clear_candidate(candidate, expected):
    keys = tuple(expected)
    candidate = _retained_mapping(candidate, keys, (), "candidate clear spacing")
    for key in keys:
        label = f"candidate clear spacing.{key}"
        if key == "pairs":
            items = _sequence(candidate[key], label)
            if len(items) != len(expected[key]):
                raise TraceValidationError(f"{label} cardinality differs")
            for index, (actual, wanted) in enumerate(zip(items, expected[key])):
                _validate_pair(actual, wanted, f"{label}[{index}]")
        elif key == "governing":
            if expected[key] is None:
                if candidate[key] is not None:
                    raise TraceValidationError(f"{label} must be null")
            else:
                _validate_pair(candidate[key], expected[key], label)
        elif key in {"limitations", "invalid_ids"}:
            _compare_text_list(candidate[key], expected[key], label)
        else:
            _compare_value(candidate[key], expected[key], label)


# ---------------------------------------------------------------------------
# Transverse-links member.
# ---------------------------------------------------------------------------

def _transverse_state(inp):
    edition = _edition(inp)
    member = str(
        inp.get("detailing_member_type", detailing.MEMBER_BEAM)
        or detailing.MEMBER_BEAM
    ).strip().title()
    if member not in detailing.MEMBER_TYPES:
        raise TraceValidationError("member_type must be Beam or Slab")
    ductility = str(
        inp.get("transverse_ductility_class", "B") or "B"
    ).strip().upper()
    if ductility not in DUCTILITY_CLASSES:
        raise TraceValidationError("ductility class must be A, B or C")
    return dict(
        edition=edition,
        member=member,
        ductility=ductility,
        apply_reduction=_boolean(
            inp.get("transverse_apply_ductility_reduction", False),
            "transverse_apply_ductility_reduction",
        ),
        fywk=_finite(inp.get("shear_fywk"), "shear_fywk"),
        diameter=_finite(inp.get("shear_link_dia"), "shear_link_dia"),
        spacing=_finite(inp.get("shear_link_s"), "shear_link_s"),
        shear_on=_boolean(inp.get("shear_on"), "shear_on"),
        shear_links=_boolean(inp.get("shear_links"), "shear_links"),
        torsion_on=_boolean(inp.get("torsion_on"), "torsion_on"),
    )


def _concrete_identity(inp):
    block = concrete_material_block(inp)
    source = block.provenance.source
    if source.citation is not None and "2023" in source.citation.document:
        raise TraceValidationError(
            "2023 material provenance is published but not implemented for CT-008"
        )
    return block


def _direction_detailing_depths(direction):
    depths = []
    for candidate in direction.get("face_candidates") or []:
        candidate = _mapping(candidate, "shear face candidate")
        shear = candidate.get("shear") or {}
        value = _upstream_scalar(_mapping(shear, "face-candidate shear").get("d"),
                                 "face-candidate d")
        if value is not None and math.isfinite(value) and value > 0.0:
            depths.append(value)
    value = _upstream_scalar(direction.get("d"), "shear direction d")
    if value is not None and math.isfinite(value) and value > 0.0:
        depths.append(value)
    return depths


def _upstream_directions(inp, out, state):
    shear_out = out.get("shear") or {}
    if not (state["shear_on"] and shear_out):
        return ()
    shear_out = _mapping(shear_out, "retained shear result")
    directions = shear_out.get("directions")
    if directions:
        items = list(_mapping(directions, "shear directions").items())
    else:
        component = str(shear_out.get("component") or (
            "vy" if shear_out.get("axis") == "x" else "vx"
        ))
        items = [(component, shear_out)]
    built = []
    for component, direction in items:
        if component not in {"vx", "vy"}:
            raise TraceValidationError(
                f"unsupported retained shear component {component!r}"
            )
        direction = _mapping(direction, f"shear direction {component}")
        links = _mapping(direction.get("links") or {}, "direction links")
        resistance = _mapping(direction.get("res") or {}, "direction res")
        resistance_valid = bool(resistance.get("valid"))
        vrd_c = _upstream_scalar(resistance.get("vrd_c"), "vrd_c")
        v_ed = _upstream_scalar(direction.get("v_ed"), "v_ed")
        if (resistance_valid and vrd_c is not None and v_ed is not None
                and math.isfinite(vrd_c) and math.isfinite(v_ed)):
            links_required = v_ed > vrd_c + 1.0e-9
        else:
            links_required = None
        model = bool(direction.get("model_2023"))
        bw = _upstream_scalar(direction.get("bw", 0.0), "direction bw")
        fallback_legs = _upstream_scalar(
            inp.get("shear_vx_link_legs" if component == "vx"
                    else "shear_vy_link_legs", 0.0),
            f"{component} fallback legs",
        )
        if fallback_legs is not None and not math.isfinite(fallback_legs):
            raise TraceValidationError(f"{component} fallback legs must be finite")
        fallback_spacing = _upstream_scalar(
            inp.get("shear_vx_transverse_leg_spacing" if component == "vx"
                    else "shear_vy_transverse_leg_spacing", 0.0),
            f"{component} transverse leg spacing",
        )
        if fallback_spacing is not None and not math.isfinite(fallback_spacing):
            raise TraceValidationError(
                f"{component} transverse leg spacing must be finite"
            )
        if "legs" in links:
            legs = _upstream_scalar(links.get("legs"), "direction legs")
            legs_from = "links" if _bindable(legs) else ""
        else:
            legs = fallback_legs
            legs_from = "fallback" if legs is not None else ""
        depths = _direction_detailing_depths(direction)
        depth = min(depths, default=0.0)
        spec = {
            "component": component,
            "links_present": state["shear_links"],
            "links_required": links_required,
            "requirement_clause": "8.2.2" if model else "6.2.2",
            "bw_mm": direction.get("bw", 0.0),
            "d_mm": depth,
            "legs": legs,
            "transverse_leg_spacing_mm": fallback_spacing,
            "measurement_axis": "y" if component == "vx" else "x",
        }
        built.append(dict(
            shape=DirectionShape(
                component=component,
                has_bw=_bindable(bw),
                has_vrd_c=_bindable(vrd_c),
                has_v_ed=_bindable(v_ed),
                legs_from=legs_from,
                depth_count=len(depths),
                has_fallback_legs=fallback_legs is not None,
                has_fallback_spacing=fallback_spacing is not None,
            ),
            spec=spec, bw=bw, resistance_valid=resistance_valid, vrd_c=vrd_c,
            v_ed=v_ed, model=model, legs=legs, depths=depths, depth=depth,
            links_required=links_required, fallback_legs=fallback_legs,
            fallback_spacing=fallback_spacing,
        ))
    return tuple(built)


def _tube_record(label, valid, reason, tube):
    tef = _upstream_scalar(tube.get("tef", 0.0), "tube tef")
    uk = _upstream_scalar(tube.get("uk", 0.0), "tube uk", allow_none=False)
    uk_mm = uk * 1000.0
    minimum = _upstream_scalar(
        tube.get("minimum_dimension_mm", 0.0), "tube minimum dimension"
    )
    spec = {
        "label": label,
        "valid": valid,
        "reason": reason,
        "tef_mm": tef,
        "uk_mm": uk_mm,
        "minimum_dimension_mm": minimum,
    }
    shape = TubeShape(
        has_uk=math.isfinite(uk_mm),
        has_tef=_bindable(tef),
        has_minimum_dimension=_bindable(minimum),
        valid=bool(valid),
        # The kernel reads the reason only on the invalid path; bind exactly
        # the string it would publish so a changed reason changes the seal.
        reason="" if valid else str(reason or "invalid torsion tube"),
    )
    return dict(shape=shape, spec=spec, tef=tef, uk_mm=uk_mm, minimum=minimum,
                valid=valid)


def _upstream_tubes(out, state):
    torsion_out = out.get("torsion") or {}
    if not (state["torsion_on"] and torsion_out):
        return ()
    torsion_out = _mapping(torsion_out, "retained torsion result")
    subresults = torsion_out.get("subtubes") or []
    built = []
    if subresults:
        for index, subresult in enumerate(_sequence(subresults, "subtubes"),
                                          start=1):
            subresult = _mapping(subresult, f"subtube {index}")
            tube = _mapping(subresult.get("tube") or {}, f"subtube {index} tube")
            built.append(_tube_record(
                f"Tube {index}",
                bool(subresult.get("valid") and tube.get("valid")),
                tube.get("reason"), tube,
            ))
    else:
        tube = _mapping(torsion_out.get("tube") or {}, "torsion tube")
        built.append(_tube_record(
            "Tube",
            bool(torsion_out.get("valid") and tube.get("valid")),
            torsion_out.get("reason") or tube.get("reason"), tube,
        ))
    return tuple(built)


def _row_shapes(expected, member, directions, tubes):
    components = {item["shape"].component for item in directions}
    rows = []
    for index, row in enumerate(expected["checks"]):
        kind = row.get("kind")
        if kind not in CHECK_ROW_KEYS or tuple(row) not in CHECK_ROW_KEYS[kind]:
            raise TraceValidationError(_DRIFT)
        status = row["status"]
        utilisation = row["utilisation"]
        if utilisation is None:
            util = "absent"
        elif math.isfinite(float(utilisation)):
            util = "finite"
        else:
            util = "infinite"
        numeric = "provided_label" in row
        if "tube" in row:
            tube_index = int(row["tube"]) - 1
            if not 0 <= tube_index < len(tubes):
                raise TraceValidationError(_DRIFT)
            ref, family = f"{tube_index:02d}", "torsion"
            if row["clause"] == _SLAB_CLAUSE:
                variant = "slab-na"
            elif kind == "minimum_ratio":
                variant = "ratio" if numeric else "ratio-na"
            else:
                variant = "torsion-spacing" if numeric else "torsion-spacing-na"
            rows.append(RowShape(index, kind, family, ref, variant, util))
            continue
        ref, family = row["component"], "shear"
        if ref not in components:
            raise TraceValidationError(_DRIFT)
        if kind == "required_links":
            model = row["clause"] == "8.2.2"
            if status == "NOT ASSESSED":
                variant = "links-na"
            elif "requirement" in row:
                variant = "links-forced"
            else:
                variant = "links-required"
            rows.append(RowShape(index, kind, family, ref, variant, util,
                                 model_2023=model))
        elif kind == "minimum_link_applicability":
            rows.append(RowShape(index, kind, family, ref, "applicability",
                                 util))
        elif kind == "minimum_ratio":
            rows.append(RowShape(index, kind, family, ref,
                                 "ratio" if numeric else "ratio-na", util))
        elif kind == "longitudinal_spacing":
            rows.append(RowShape(index, kind, family, ref,
                                 "long" if numeric else "long-na", util))
        elif kind == "transverse_leg_spacing":
            if not numeric or row["provided"] is None:
                rows.append(RowShape(index, kind, family, ref, "leg-na", util))
            else:
                src_tag = "user" if row["spacing_source"] == "user" else "screen"
                has_limit = row["limit"] is not None
                demoted = (src_tag == "screen" and has_limit
                           and status == "NOT ASSESSED")
                rows.append(RowShape(index, kind, family, ref, "leg", util,
                                     has_limit=has_limit, src_tag=src_tag,
                                     demoted=demoted))
        else:
            raise TraceValidationError(_DRIFT)
    return tuple(rows)


def _replay_transverse(inp, out, context):
    _require_section(inp)
    state = _transverse_state(inp)
    block = _concrete_identity(inp)
    # The retained kernel returns INVALID from the direct inputs before
    # reading any direction/tube geometry; on that branch the upstream
    # payloads are inert and must be neither parsed, bound, nor rejected.
    fck = dict(block.values)["fck"]
    invalid_direct = any(value <= 0.0 for value in (
        fck, state["fywk"], state["diameter"], state["spacing"]))
    if invalid_direct:
        directions, tubes = (), ()
    else:
        directions = _upstream_directions(inp, out, state)
        tubes = _upstream_tubes(out, state)
    expected = detailing.transverse_reinforcement(
        edition=inp["detailing_edition"],
        fck_mpa=inp["concrete"].fck,
        fywk_mpa=inp["shear_fywk"],
        diameter_mm=inp["shear_link_dia"],
        spacing_mm=inp["shear_link_s"],
        shear_directions=[item["spec"] for item in directions],
        torsion_tubes=[item["spec"] for item in tubes],
        ductility_class=inp.get("transverse_ductility_class", "B"),
        apply_ductility_reduction=inp.get(
            "transverse_apply_ductility_reduction", False
        ),
        member_type=inp.get("detailing_member_type", detailing.MEMBER_BEAM),
    )
    invalid = tuple(expected) == TRANSVERSE_INVALID_KEYS
    if not invalid and tuple(expected) != TRANSVERSE_KEYS:
        raise TraceValidationError(_DRIFT)
    if invalid != (expected["status"] == "INVALID") or invalid != invalid_direct:
        raise TraceValidationError(_DRIFT)
    if not invalid and tuple(expected["minimum_ratio"]) != MINIMUM_RATIO_KEYS:
        raise TraceValidationError(_DRIFT)
    rows = () if invalid else _row_shapes(expected, state["member"],
                                          directions, tubes)
    governing_present = not invalid and expected["governing"] is not None
    branch = ("invalid" if invalid
              else ("not-applicable" if not rows else "checked"))
    shape = TransverseShape(
        concrete_values=block.values,
        concrete_source=block.provenance.source,
        concrete_material_id=block.material_id,
        edition=state["edition"], member=state["member"], invalid=invalid,
        directions=tuple(item["shape"] for item in directions),
        tubes=tuple(item["shape"] for item in tubes),
        rows=rows, governing_present=governing_present,
        calculation_id=f"ct-008-{context_id(context)}-transverse-links",
        axes=context_axes(
            context, detailing_edition=state["edition"],
            direction_count=str(len(directions)),
            member_type=state["member"], transverse_branch=branch,
            tube_count=str(len(tubes)),
        ),
    )
    values: dict[str, Any] = {
        "input-transverse-enabled": 1.0,
        "input-edition": float(EDITIONS.index(state["edition"])),
        "input-member-type": float(state["member"] == detailing.MEMBER_SLAB),
        "input-ductility-class": float(DUCTILITY_CLASSES.index(state["ductility"])),
        "input-apply-ductility-reduction": float(state["apply_reduction"]),
        "input-link-fywk": state["fywk"],
        "input-link-diameter": state["diameter"],
        "input-link-spacing": state["spacing"],
        "input-shear-enabled": float(state["shear_on"]),
        "input-shear-links": float(state["shear_links"]),
        "input-torsion-enabled": float(state["torsion_on"]),
        "material-vector": 1.0,
        "normalised-transverse-inputs": 1.0,
    }
    for name, value in block.values:
        values[concrete_leaf_id(block.material_id, name)] = value
    for item in directions:
        c = item["shape"].component
        if item["shape"].has_fallback_legs:
            values[f"input-{c}-fallback-legs"] = item["fallback_legs"]
        if item["shape"].has_fallback_spacing:
            values[f"input-{c}-fallback-transverse-spacing"] = (
                item["fallback_spacing"]
            )
    code = STATUS_CODES[expected["status"]]
    if invalid:
        values["invalid-input-state"] = 1.0
        values["ct-008-transverse-links-result"] = code
        return shape, MemberEvidence(values, expected)
    minimum = expected["minimum_ratio"]
    values.update({
        "link-leg-area": math.pi * state["diameter"] ** 2 / 4.0,
        "minimum-ratio-coefficient": minimum["coefficient"],
        "ductility-factor": minimum["ductility_factor"],
        "minimum-ratio": minimum["ratio"],
    })
    for item in directions:
        c = item["shape"].component
        if item["shape"].has_bw:
            values[f"upstream-shear-{c}-bw"] = item["bw"]
        values[f"upstream-shear-{c}-resistance-valid"] = float(
            item["resistance_valid"]
        )
        if item["shape"].has_vrd_c:
            values[f"upstream-shear-{c}-vrd-c"] = item["vrd_c"]
        if item["shape"].has_v_ed:
            values[f"upstream-shear-{c}-v-ed"] = item["v_ed"]
        values[f"upstream-shear-{c}-model-2023"] = float(item["model"])
        if item["shape"].legs_from == "links":
            values[f"upstream-shear-{c}-links-legs"] = item["legs"]
        for index, depth in enumerate(item["depths"]):
            values[f"upstream-shear-{c}-depth-{index:02d}"] = depth
        values[f"shear-{c}-evidence"] = 1.0
        required = item["links_required"]
        values[f"shear-{c}-links-required"] = (
            2.0 if required is None else float(required)
        )
        if item["shape"].legs_from:
            values[f"shear-{c}-legs"] = item["legs"]
        values[f"shear-{c}-detailing-depth"] = item["depth"]
    for index, item in enumerate(tubes):
        prefix = f"torsion-tube-{index:02d}"
        if item["shape"].has_uk:
            values[f"upstream-{prefix}-uk"] = item["uk_mm"]
        if item["shape"].has_tef:
            values[f"upstream-{prefix}-tef"] = item["tef"]
        if item["shape"].has_minimum_dimension:
            values[f"upstream-{prefix}-minimum-dimension"] = item["minimum"]
        values[f"upstream-{prefix}-valid"] = float(item["valid"])
        if not item["shape"].valid:
            values[tube_reason_id(index, item["shape"].reason)] = 1.0
        values[f"{prefix}-evidence"] = 1.0
    for row_shape, row in zip(rows, expected["checks"]):
        check = f"check-{row_shape.index:02d}"
        if row_shape.variant in {"ratio", "leg"}:
            values[f"{check}-provided"] = float(row["provided"])
        if row_shape.variant in {"long", "torsion-spacing"} or (
                row_shape.variant == "leg" and row_shape.has_limit):
            values[f"{check}-limit"] = float(row["limit"])
        if row_shape.util != "absent":
            values[f"{check}-utilisation"] = float(row["utilisation"])
        values[f"{check}-status"] = STATUS_CODES[row["status"]]
    values["transverse-status"] = code
    if governing_present:
        governing = expected["governing"]
        index = next(i for i, row in enumerate(expected["checks"])
                     if row is governing)
        values["governing-utilisation"] = float(governing["utilisation"])
        values["governing-check"] = float(index)
    values["ct-008-transverse-links-result"] = code
    return shape, MemberEvidence(values, expected)


def _validate_check_row(candidate, expected, label):
    candidate = _retained_mapping(candidate, tuple(expected), (), label)
    for key in tuple(expected):
        if key == "spacing_limits_mm":
            nested = _retained_mapping(candidate[key], TORSION_LIMIT_KEYS, (),
                                       f"{label}.{key}")
            for name in TORSION_LIMIT_KEYS:
                _compare_value(nested[name], expected[key][name],
                               f"{label}.{key}.{name}")
        else:
            _compare_value(candidate[key], expected[key], f"{label}.{key}")


def _validate_transverse_candidate(candidate, expected):
    keys = tuple(expected)
    candidate = _retained_mapping(candidate, keys, (),
                                  "candidate transverse reinforcement")
    for key in keys:
        label = f"candidate transverse reinforcement.{key}"
        if key == "checks":
            items = _sequence(candidate[key], label)
            if len(items) != len(expected[key]):
                raise TraceValidationError(f"{label} cardinality differs")
            for index, (actual, wanted) in enumerate(zip(items, expected[key])):
                _validate_check_row(actual, wanted, f"{label}[{index}]")
        elif key == "governing":
            if expected[key] is None:
                if candidate[key] is not None:
                    raise TraceValidationError(f"{label} must be null")
            else:
                _validate_check_row(candidate[key], expected[key], label)
        elif key == "minimum_ratio":
            nested = _retained_mapping(candidate[key], MINIMUM_RATIO_KEYS, (),
                                       label)
            for name in MINIMUM_RATIO_KEYS:
                _compare_value(nested[name], expected[key][name],
                               f"{label}.{name}")
        elif key == "limitations":
            _compare_text_list(candidate[key], expected[key], label)
        else:
            _compare_value(candidate[key], expected[key], label)


# ---------------------------------------------------------------------------
# Longitudinal minimum-reinforcement member.
# ---------------------------------------------------------------------------

_LONG_ROW_KEYS = {
    "row-2005": ROW_2005_KEYS,
    "2023-tension": ROW_2023_TENSION_KEYS,
    "2023-bending": ROW_2023_BENDING_KEYS,
}


def _compare_numeric_list(actual, expected, label):
    if expected is None:
        if actual is not None:
            raise TraceValidationError(f"{label} must be null")
        return
    items = _sequence(actual, label)
    if len(items) != len(expected):
        raise TraceValidationError(f"{label} cardinality differs")
    for index, (item, wanted) in enumerate(zip(items, expected)):
        _compare_value(item, wanted, f"{label}[{index}]")


def _finite_number(value: Any) -> bool:
    return (type(value) in {int, float} and type(value) is not bool
            and math.isfinite(float(value)))


def _long_state(inp):
    edition = _edition(inp)
    member = str(
        inp.get("detailing_member_type", detailing.MEMBER_BEAM)
        or detailing.MEMBER_BEAM
    ).strip().title()
    if member not in detailing.MEMBER_TYPES:
        raise TraceValidationError("member_type must be Beam or Slab")
    cut = str(
        inp.get("detailing_cut_direction", detailing.CUT_TRANSVERSE)
        or detailing.CUT_TRANSVERSE
    ).strip()
    if cut not in detailing.CUT_DIRECTIONS:
        raise TraceValidationError("unknown section cut direction")
    return dict(
        edition=edition, member=member, cut=cut,
        fctm=_finite(inp.get("sls_fctm"), "sls_fctm"),
        axial=_finite(inp.get("P_pl"), "P_pl"),
        mx=_finite(inp.get("Mx_pl"), "Mx_pl"),
        my=_finite(inp.get("My_pl"), "My_pl"),
    )


def _long_branch(state, expected):
    keys = tuple(expected)
    if state["member"] == detailing.MEMBER_SLAB and (
            state["cut"] == detailing.CUT_LONGITUDINAL):
        if keys != LONG_SLAB_CUT_KEYS:
            raise TraceValidationError(_DRIFT)
        return "slab-cut"
    if state["edition"] != detailing.EC2_2023:
        if keys != LONG_2005_KEYS:
            raise TraceValidationError(_DRIFT)
        return "row-2005" if expected["checks"] else "2005-zero"
    if keys == LONG_2023_HIGH_COMPRESSION_KEYS:
        return "2023-high-compression"
    if keys == LONG_2023_BENDING_KEYS:
        return "2023-bending"
    if keys == LONG_2023_SCOPE_KEYS:
        # The 12.2(5) scope-out shape is unique; the retained Slab dispatch
        # overwrites its clause in place, so the clause text is a replayed
        # retained value, never a branch selector.
        return "2023-compression-only"
    if keys == LONG_2005_KEYS:
        if expected["checks"]:
            return "2023-tension"
        if expected["status"] == "INVALID":
            return "2023-invalid"
    raise TraceValidationError(_DRIFT)


def _replay_longitudinal(inp, context):
    _require_section(inp)
    state = _long_state(inp)
    concrete = _concrete_identity(inp)
    section = inp["section"]
    blocks = bar_material_blocks(
        inp, kind="bar", count=len(section.bars), default=inp.get("steel")
    )
    for block in blocks:
        source = block.provenance.source
        if source.citation is not None and "2023" in source.citation.document:
            raise TraceValidationError(
                "2023 material provenance is published but not implemented "
                "for CT-008"
            )
    geometry = GeometryBlock.from_section(section)
    expected = detailing.minimum_reinforcement(
        section,
        inp.get("bar_elements") or [],
        inp.get("bar_materials") or [],
        inp["concrete"],
        edition=inp["detailing_edition"],
        fctm_mpa=inp["sls_fctm"],
        n_ed_tension_kn=inp["P_pl"],
        mx_ed_knm=inp["Mx_pl"],
        my_ed_knm=inp["My_pl"],
        member_type=inp.get("detailing_member_type", detailing.MEMBER_BEAM),
        cut_direction=inp.get("detailing_cut_direction",
                              detailing.CUT_TRANSVERSE),
    )
    branch = _long_branch(state, expected)
    row = None
    if branch in _LONG_ROW_KEYS:
        checks = expected["checks"]
        if len(checks) != 1 or tuple(checks[0]) != _LONG_ROW_KEYS[branch]:
            raise TraceValidationError(_DRIFT)
        row = checks[0]
    elif expected["checks"]:
        raise TraceValidationError(_DRIFT)
    row_fields = tuple(
        field for field in LONG_ROW_FIELD_CANDIDATES.get(branch, ())
        if row is not None and _finite_number(row.get(field))
    )
    shape = LongShape(
        concrete_values=concrete.values,
        concrete_source=concrete.provenance.source,
        concrete_material_id=concrete.material_id,
        bars=tuple(BarIdentity(block.element_id, block.material_id,
                               block.values, block.provenance.source)
                   for block in blocks),
        ring_points=tuple(len(ring) for ring in geometry.rings),
        edition=state["edition"], member=state["member"], cut=state["cut"],
        branch=branch, row_fields=row_fields,
        has_compression_limit="compression_limit_kn" in expected,
        calculation_id=f"ct-008-{context_id(context)}-longitudinal-minimum",
        axes=context_axes(
            context, cut_direction=state["cut"],
            detailing_edition=state["edition"], longitudinal_branch=branch,
            member_type=state["member"],
        ),
    )
    values: dict[str, Any] = {
        "input-minimum-enabled": 1.0,
        "input-edition": float(EDITIONS.index(state["edition"])),
        "input-member-type": float(state["member"] == detailing.MEMBER_SLAB),
        "input-cut-direction": float(
            detailing.CUT_DIRECTIONS.index(state["cut"])
        ),
        "input-fctm": state["fctm"],
        "input-axial-action": state["axial"],
        "input-mx-action": state["mx"],
        "input-my-action": state["my"],
        "geometry-vector": 1.0,
        "material-vector": 1.0,
        "normalised-longitudinal-inputs": 1.0,
    }
    for ring_index, ring in enumerate(geometry.rings):
        for point_index, point in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            values[f"{prefix}-x"], values[f"{prefix}-y"] = point
    for index, bar in enumerate(geometry.bars):
        prefix = f"geometry-bar-{index:03d}"
        values.update({f"{prefix}-x": bar.x, f"{prefix}-y": bar.y,
                       f"{prefix}-area": bar.area})
    for name, value in concrete.values:
        values[concrete_leaf_id(concrete.material_id, name)] = value
    for block in blocks:
        for name, value in block.values:
            values[bar_leaf_id(block.element_id, block.material_id,
                               name)] = value
    code = STATUS_CODES[expected["status"]]
    if branch == "slab-cut":
        values["slab-cut-scope"] = 1.0
        values["ct-008-longitudinal-minimum-result"] = code
        return shape, MemberEvidence(values, expected)
    values["mx-centroid"] = expected["mx_ed_centroid_knm"]
    values["my-centroid"] = expected["my_ed_centroid_knm"]
    if shape.has_compression_limit:
        values["compression-limit"] = expected["compression_limit_kn"]
    if row is None:
        values["assessment-scope-state"] = 1.0
    else:
        values["assessment-basis"] = 1.0
        for field in row_fields:
            values[long_field_step_id(field)] = float(row[field])
        values["row-status"] = STATUS_CODES[row["status"]]
        values["longitudinal-status"] = code
    values["ct-008-longitudinal-minimum-result"] = code
    return shape, MemberEvidence(values, expected)


def _validate_long_row(candidate, expected, label):
    candidate = _retained_mapping(candidate, tuple(expected), (), label)
    for key in tuple(expected):
        if key in {"bar_ids", "material_ids"}:
            _compare_text_list(candidate[key], expected[key], f"{label}.{key}")
        elif key in {"tension_direction", "neutral_point_m"}:
            _compare_numeric_list(candidate[key], expected[key],
                                  f"{label}.{key}")
        else:
            _compare_value(candidate[key], expected[key], f"{label}.{key}")


def _validate_longitudinal_candidate(candidate, expected):
    keys = tuple(expected)
    candidate = _retained_mapping(candidate, keys, (),
                                  "candidate minimum reinforcement")
    for key in keys:
        label = f"candidate minimum reinforcement.{key}"
        if key == "checks":
            items = _sequence(candidate[key], label)
            if len(items) != len(expected[key]):
                raise TraceValidationError(f"{label} cardinality differs")
            for index, (actual, wanted) in enumerate(zip(items, expected[key])):
                _validate_long_row(actual, wanted, f"{label}[{index}]")
        elif key == "limitations":
            _compare_text_list(candidate[key], expected[key], label)
        else:
            _compare_value(candidate[key], expected[key], label)


# ---------------------------------------------------------------------------
# Bundle assembly.
# ---------------------------------------------------------------------------

def _expression(step_id: str, title: str) -> str:
    expressions = {
        "governing-margin": "governing margin = min(pair margins)",
        "-links-required": "VEd > VRd,c + 1e-9 (1 = yes, 0 = no, 2 = unknown)",
        "-centre-distance": "centre = hypot(x2 - x1, y2 - y1)",
        "-clear": "clear = centre - (phi1 + phi2)/2",
        "-required": "required = max(max(phi1, phi2), Dupper + 5, 20)",
        "-margin": "margin = clear - required",
        "link-leg-area": "A_leg = pi*dia^2/4",
        "minimum-ratio": "rho_w,min = c*sqrt(fck)/fywk*k_duct",
        "-detailing-depth": "d = min(retained positive face depths, default 0)",
        "-utilisation": "utilisation = provided-versus-limit ratio",
    }
    for suffix, expression in expressions.items():
        if step_id.endswith(suffix) or step_id == suffix:
            return expression
    if step_id.endswith("-status") or step_id.endswith("-result") or (
            step_id.endswith("-verdict")):
        return ("retained status code: PASS=1, FAIL=0, REVIEW=2, "
                "NOT ASSESSED=3, NOT APPLICABLE=4, INVALID=5")
    return f"Bind {title.lower()}"


def _calculation(calculation_id, title, axes, specs, values, assumptions):
    units = {spec.step_id: spec.unit for spec in specs}
    steps = []
    for spec in specs:
        value = values[spec.step_id]
        numeric = float(value)
        if math.isinf(numeric):
            result = TraceResult(RESULT_POSITIVE_INFINITY, None,
                                 _INFINITE_REASON)
            substituted = f"{spec.step_id} = positive_infinity"
        else:
            result = TraceResult(RESULT_FINITE, numeric)
            substituted = f"{spec.step_id} = {numeric:.17g} {spec.unit.symbol}"
        steps.append(TraceStep(
            spec.step_id, spec.title,
            tuple(TraceDependency(name, units[name])
                  for name in spec.dependencies),
            spec.quantity_role, spec.source, spec.step_id, spec.unit,
            _expression(spec.step_id, spec.title), substituted, result,
        ))
    return TraceCalculation(
        calculation_id, COVERAGE_ID, title, METHOD_ID, axes,
        steps[-1].step_id, tuple(steps), (), assumptions,
    )


_CLEAR_ASSUMPTIONS = (
    "Pairwise edge-to-edge distance is checked in the section plane; lap "
    "length, bundle arrangement and bond are outside CT-008.",
)
_TRANSVERSE_ASSUMPTIONS = (
    "Adapter-consumed shear and torsion values are upstream evidence "
    "validated by the accepted CT-006/CT-007 families and are not "
    "re-derived here.",
)


def _absent_candidates(members, out):
    for member_id, key in ((CLEAR_MEMBER_ID, "clear_spacing"),
                           (TRANSVERSE_MEMBER_ID, "transverse_reinforcement"),
                           (LONGITUDINAL_MEMBER_ID, "minimum_reinforcement")):
        if member_id not in members and out.get(key) is not None:
            raise TraceValidationError(
                f"absent CT-008 {member_id} flag cannot carry a candidate"
            )


_LONG_ASSUMPTIONS = (
    "The 2023 nominal-capacity and cracking solves run only inside the "
    "retained kernel; the trace replays the same authoritative call.",
)


def _expected_bundle(inp, out, members, input_sha256, result_sha256, context):
    calculations = []
    clear_shape = transverse_shape = longitudinal_shape = None
    if CLEAR_MEMBER_ID in members:
        clear_shape, evidence = _replay_clear(inp, context)
        _validate_clear_candidate(out.get("clear_spacing"), evidence.expected)
        calculations.append(_calculation(
            clear_shape.calculation_id, "Clear bar spacing detailing",
            clear_shape.axes, expected_clear_steps(clear_shape),
            evidence.values, _CLEAR_ASSUMPTIONS,
        ))
    if TRANSVERSE_MEMBER_ID in members:
        transverse_shape, evidence = _replay_transverse(inp, out, context)
        _validate_transverse_candidate(
            out.get("transverse_reinforcement"), evidence.expected
        )
        calculations.append(_calculation(
            transverse_shape.calculation_id, "Transverse link detailing",
            transverse_shape.axes, expected_transverse_steps(transverse_shape),
            evidence.values, _TRANSVERSE_ASSUMPTIONS,
        ))
    if LONGITUDINAL_MEMBER_ID in members:
        longitudinal_shape, evidence = _replay_longitudinal(inp, context)
        _validate_longitudinal_candidate(
            out.get("minimum_reinforcement"), evidence.expected
        )
        calculations.append(_calculation(
            longitudinal_shape.calculation_id,
            "Longitudinal minimum reinforcement", longitudinal_shape.axes,
            expected_longitudinal_steps(longitudinal_shape),
            evidence.values, _LONG_ASSUMPTIONS,
        ))
    bundle = create_bundle(
        input_sha256=input_sha256, result_sha256=result_sha256,
        calculations=tuple(calculations),
    )
    audit_trace_registry(bundle, expected_registry(DetailingShape(
        clear_shape, transverse_shape, longitudinal_shape
    )))
    return bundle


def build_detailing_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build and seal the applicable CT-008 detailing family."""

    try:
        out = _mapping(out, "retained result mapping")
        members = detailing_trace_applicability(inp)
        _absent_candidates(members, out)
        if not members:
            return None
        return _expected_bundle(inp, out, members, input_sha256,
                                result_sha256, {} if context is None else context)
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-008 detailing evidence: {exc}") from exc


def validate_detailing_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Reject stale or coherently resealed CT-008 value/graph/source tampering."""

    out = _mapping(out, "retained result mapping")
    members = detailing_trace_applicability(inp)
    _absent_candidates(members, out)
    if not members:
        if bundle is not None:
            raise TraceValidationError(
                "not-applicable CT-008 input cannot carry a trace"
            )
        return None
    candidate = validate_bundle(
        bundle, expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected = build_detailing_trace_family(
        inp, out, input_sha256=input_sha256, result_sha256=result_sha256,
        context=context,
    )
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError(
            "CT-008 trace differs from authoritative input replay"
        )
    return candidate
