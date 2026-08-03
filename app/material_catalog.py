"""Pure helpers for stable reinforcing- and prestressing-steel catalogues.

The UI stores catalogues as JSON-native mappings so project files can preserve
several independently defined material laws.  Reinforcement elements refer to a
stable material ID; display names may therefore be edited without breaking the
assignment.  This module deliberately has no Streamlit dependency.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Iterable, Mapping, Sequence

from sector import codes, material_presets as mp


VERSION = 1
KINDS = ("mild", "prestress")

MILD_CATALOG_KEY = "mild_material_catalog"
PRESTRESS_CATALOG_KEY = "prestress_material_catalog"
CATALOG_KEYS = (MILD_CATALOG_KEY, PRESTRESS_CATALOG_KEY)

DEFAULT_MILD_PRESET = "DS/EN 1992-1-1:2005 + DK NA:2024"
DEFAULT_PRESTRESS_PRESET = "EN 1992-1-1:2005"

MILD_FIELDS = tuple(mp.MILD_FIELD_META)
PRESTRESS_FIELDS = tuple(mp.PRESTRESS_FIELD_META)


def mild_preset_classification(preset: str) -> str:
    """Return the user-facing identity of a mild-steel preset selection.

    Identity follows the concrete selected preset, never numerical similarity.
    Every current preset happens to use the general Curve-3 kernel, but the named
    generic shapes remain project-defined while edition names retain their own
    Eurocode provenance.
    """

    selected = str(preset).strip()
    if selected in codes.CODES:
        return "Curve 3 Eurocode design preset"
    if selected == "Curve 2 (elastic-perfectly-plastic)":
        return "User-defined / project-defined Curve 2 preset; uncited"
    if selected in mp.MILD_PRESETS:
        return "User-defined / project-defined named-curve preset; uncited"
    return "Custom / imported user law; uncited"


def mild_preset_display_label(preset: str) -> str:
    """Decorate a mild preset for display without changing its stored value."""

    selected = str(preset).strip()
    return f"{selected} [{mild_preset_classification(selected)}]"


def mild_preset_kernel_note(preset: str) -> str:
    """Describe the common kernel without claiming that editable values are fixed."""

    selected = str(preset).strip()
    if selected in codes.CODES:
        return ("General Curve 3 law; the edition preset supplies Eurocode "
                "design-diagram starting values")
    if selected in mp.MILD_PRESETS:
        return ("General Curve 3 law; the named project-defined preset supplies "
                "starting values")
    return "Stored material-law inputs; no standard identity inferred"


def _kind(kind: str) -> str:
    value = str(kind).strip().lower()
    if value not in KINDS:
        raise ValueError(f"unknown material kind: {kind}")
    return value


def catalog_key(kind: str) -> str:
    return MILD_CATALOG_KEY if _kind(kind) == "mild" else PRESTRESS_CATALOG_KEY


def id_prefix(kind: str) -> str:
    return "M" if _kind(kind) == "mild" else "P"


def default_preset(kind: str) -> str:
    return DEFAULT_MILD_PRESET if _kind(kind) == "mild" else DEFAULT_PRESTRESS_PRESET


def presets(kind: str) -> Mapping[str, Mapping]:
    return mp.MILD_PRESETS if _kind(kind) == "mild" else mp.PRESTRESS_PRESETS


def fields(kind: str) -> tuple[str, ...]:
    return MILD_FIELDS if _kind(kind) == "mild" else PRESTRESS_FIELDS


def curves(kind: str) -> tuple[int, ...]:
    return (1, 2, 3) if _kind(kind) == "mild" else (1, 2, 3, 4, 5, 6, 7)


def _finite(value, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return number if math.isfinite(number) else float(fallback)


def _text(value, fallback: str = "") -> str:
    return str(value).strip() if value is not None else fallback


def _entry_defaults(kind: str, preset: str | None = None) -> dict:
    kind = _kind(kind)
    available = presets(kind)
    selected = str(preset or default_preset(kind))
    if selected not in available:
        selected = default_preset(kind)
    values = dict(available[selected])
    name = "B550 reinforcement" if kind == "mild" else "Prestressing steel"
    out = {
        "id": f"{id_prefix(kind)}1",
        "name": name,
        "description": "",
        "preset": selected,
        "curve": int(values["curve"]),
    }
    if kind == "mild":
        out["active_in_compression"] = True
    for field in fields(kind):
        # Some fixed built-in prestress curves do not carry inert parametric
        # fields.  Seed those from the default general law so the flat editor is
        # stable when the user changes preset later.
        fallback = available[default_preset(kind)].get(field, 0.0)
        out[field] = _finite(values.get(field, fallback), fallback)
    return out


def default_entry(kind: str, *, material_id: str | None = None,
                  preset: str | None = None) -> dict:
    out = _entry_defaults(kind, preset)
    if material_id:
        out["id"] = str(material_id)
    return out


def default_catalog(kind: str) -> dict:
    return {"version": VERSION, "next_id": 2, "items": [default_entry(kind)]}


def _source_items(value) -> list[Mapping]:
    if isinstance(value, Mapping):
        items = value.get("items", [])
    else:
        items = value
    if isinstance(items, Mapping):
        items = [items]
    if not isinstance(items, Iterable) or isinstance(items, (str, bytes)):
        return []
    return [item for item in items if isinstance(item, Mapping)]


def _normalise_entry(raw: Mapping, kind: str, material_id: str) -> dict:
    kind = _kind(kind)
    available = presets(kind)
    selected = _text(raw.get("preset"), default_preset(kind))
    if selected not in available:
        # Preserve the numerical law but report it as custom rather than assigning
        # a different named standard to imported values.
        selected = "Custom / imported"
    preset_values = available.get(selected, available[default_preset(kind)])
    base = _entry_defaults(kind, selected if selected in available else None)
    curve = int(_finite(raw.get("curve", preset_values.get("curve", 3)),
                        preset_values.get("curve", 3)))
    if curve not in curves(kind):
        # Keep a recognised preset internally consistent when a damaged import
        # carries an impossible curve number. Custom imports fall back to the
        # default general law via ``preset_values``.
        curve = int(preset_values["curve"])
    base.update({
        "id": material_id,
        "name": _text(raw.get("name"), base["name"]) or base["name"],
        "description": _text(raw.get("description")),
        "preset": selected,
        "curve": curve,
    })
    if kind == "mild":
        base["active_in_compression"] = bool(
            raw.get("active_in_compression", raw.get("active_comp", True))
        )
    for field in fields(kind):
        fallback = base[field]
        base[field] = _finite(raw.get(field, fallback), fallback)
    return base


def normalise_catalog(value, kind: str) -> dict:
    """Return a canonical catalogue with stable, unique material IDs."""
    kind = _kind(kind)
    source = _source_items(value)
    if not source:
        return default_catalog(kind)
    prefix = id_prefix(kind)
    pattern = re.compile(rf"^{prefix}([1-9][0-9]*)$")
    valid_numbers = [int(match.group(1)) for item in source
                     if (match := pattern.fullmatch(_text(item.get("id"))))]
    next_number = max(valid_numbers, default=0) + 1
    used: set[str] = set()
    items = []
    for raw in source:
        material_id = _text(raw.get("id"))
        if not pattern.fullmatch(material_id) or material_id in used:
            while f"{prefix}{next_number}" in used:
                next_number += 1
            material_id = f"{prefix}{next_number}"
            next_number += 1
        used.add(material_id)
        items.append(_normalise_entry(raw, kind, material_id))
    requested_next = value.get("next_id") if isinstance(value, Mapping) else None
    try:
        requested_next = int(requested_next)
    except (TypeError, ValueError):
        requested_next = 1
    next_number = max(next_number, requested_next, 1)
    while f"{prefix}{next_number}" in used:
        next_number += 1
    return {"version": VERSION, "next_id": next_number, "items": items}


def ensure_catalog(scalars: Mapping, kind: str) -> dict:
    """Return the current catalogue or initialise a current-schema default."""
    key = catalog_key(kind)
    if key in scalars:
        return normalise_catalog(scalars[key], kind)
    return default_catalog(kind)


def entries(catalog, kind: str) -> list[dict]:
    return normalise_catalog(catalog, kind)["items"]


def entry_map(catalog, kind: str) -> dict[str, dict]:
    return {item["id"]: item for item in entries(catalog, kind)}


def entry_label(entry: Mapping) -> str:
    return f"{entry.get('id', '')} - {entry.get('name', '')}".strip()


def material_ids(catalog, kind: str) -> list[str]:
    return [item["id"] for item in entries(catalog, kind)]


def assigned_counts(material_ids_: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for material_id in material_ids_:
        value = str(material_id).strip()
        counts[value] = counts.get(value, 0) + 1
    return counts


def invalid_assignments(material_ids_: Sequence[str], catalog, kind: str) -> list[str]:
    available = set(material_ids(catalog, kind))
    return sorted({str(value).strip() for value in material_ids_
                   if str(value).strip() not in available})


def _next_id(catalog: Mapping, kind: str) -> tuple[str, int]:
    canonical = normalise_catalog(catalog, kind)
    used = {item["id"] for item in canonical["items"]}
    number = int(canonical["next_id"])
    prefix = id_prefix(kind)
    while f"{prefix}{number}" in used:
        number += 1
    return f"{prefix}{number}", number + 1


def add_entry(catalog, kind: str, *, preset: str | None = None) -> tuple[dict, str]:
    canonical = normalise_catalog(catalog, kind)
    material_id, next_number = _next_id(canonical, kind)
    item = default_entry(kind, material_id=material_id, preset=preset)
    ordinal = len(canonical["items"]) + 1
    item["name"] = (f"Reinforcement material {ordinal}" if _kind(kind) == "mild"
                    else f"Prestressing material {ordinal}")
    canonical["items"].append(item)
    canonical["next_id"] = next_number
    return canonical, material_id


def duplicate_entry(catalog, kind: str, material_id: str) -> tuple[dict, str]:
    canonical = normalise_catalog(catalog, kind)
    source = next((item for item in canonical["items"]
                   if item["id"] == material_id), None)
    if source is None:
        raise KeyError(material_id)
    new_id, next_number = _next_id(canonical, kind)
    item = copy.deepcopy(source)
    item["id"] = new_id
    item["name"] = f"{source['name']} copy"
    canonical["items"].append(item)
    canonical["next_id"] = next_number
    return canonical, new_id


def delete_entry(catalog, kind: str, material_id: str,
                 *, assigned_ids: Sequence[str] = ()) -> dict:
    canonical = normalise_catalog(catalog, kind)
    if len(canonical["items"]) <= 1:
        raise ValueError("at least one material must remain")
    if material_id in {str(value).strip() for value in assigned_ids}:
        raise ValueError("material is assigned to an element")
    kept = [item for item in canonical["items"] if item["id"] != material_id]
    if len(kept) == len(canonical["items"]):
        raise KeyError(material_id)
    canonical["items"] = kept
    return canonical


def replace_entry(catalog, kind: str, entry: Mapping) -> dict:
    canonical = normalise_catalog(catalog, kind)
    material_id = _text(entry.get("id"))
    found = False
    items = []
    for item in canonical["items"]:
        if item["id"] == material_id:
            items.append(_normalise_entry(entry, kind, material_id))
            found = True
        else:
            items.append(item)
    if not found:
        raise KeyError(material_id)
    canonical["items"] = items
    return canonical


def apply_preset(entry: Mapping, kind: str, preset: str) -> dict:
    """Prefill numerical law fields while retaining ID, name and description."""
    available = presets(kind)
    if preset not in available:
        raise KeyError(preset)
    out = dict(entry)
    values = available[preset]
    out["preset"] = preset
    out["curve"] = int(values["curve"])
    for field in fields(kind):
        if field in values:
            out[field] = float(values[field])
    if _kind(kind) == "mild" and values.get("fyck", 0.0) > 0.0:
        out["active_in_compression"] = True
    return _normalise_entry(out, kind, _text(out.get("id")))


def build_material(entry: Mapping, kind: str):
    item = _normalise_entry(entry, kind, _text(entry.get("id")))
    values = {field: item[field] for field in fields(kind)}
    if _kind(kind) == "mild":
        return mp.build_mild(
            item["curve"], active_in_compression=item["active_in_compression"],
            **values,
        )
    return mp.build_prestress(item["curve"], **values)


def signature(catalog, kind: str) -> tuple:
    canonical = normalise_catalog(catalog, kind)
    keys = ("id", "name", "description", "preset", "curve")
    if _kind(kind) == "mild":
        keys += ("active_in_compression",)
    keys += fields(kind)
    return tuple(tuple(item.get(key) for key in keys)
                 for item in canonical["items"])
