"""Canonical fatigue-detail catalogues and grouped action spectra.

Fatigue resistance is not a constitutive material property.  Reinforcement
elements therefore keep their material-law ID and refer separately to a stable
fatigue-detail ID.  A grouped spectrum contains one row per constant-amplitude
bin.  Its section-force columns deliberately match the Elastic solver's
long-term/short-term convention:

* ``long`` is the non-cyclic basic state;
* ``short`` is the cyclic increment; and
* the combined state is ``long + short``.

The pure helpers in this module are shared by project I/O, the forthcoming
fatigue engine and the Streamlit interface.  They do not select authority load
models or alter user-entered partial factors.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Iterable, Mapping, Sequence

import pandas as pd


VERSION = 1

DETAIL_CATALOG_KEY = "fatigue_detail_catalog"
SPECTRUM_TABLE_KEY = "fatigue_spectrum_base"

MILD = "mild"
PRESTRESS = "prestress"
KINDS = (MILD, PRESTRESS)

FIXED_STRESS = "fixed"
EC2_2023_BAR_STRESS = "ec2_2023_bar_diameter"
EC2_2023_WELDED_STRESS = "ec2_2023_welded_diameter"
STRESS_MODELS = (
    FIXED_STRESS,
    EC2_2023_BAR_STRESS,
    EC2_2023_WELDED_STRESS,
)

EC2_2005 = "DS/EN 1992-1-1:2005"
EC2_2023 = "DS/EN 1992-1-1:2023"

PRESET_2005_BARS = "EC2:2005 - straight reinforcing bars"
PRESET_2005_BENT_BARS = "EC2:2005 - bent reinforcing bars"
PRESET_2005_WELDED = "EC2:2005 - welded bars and fabrics"
PRESET_2005_COUPLERS = "EC2:2005 - reinforcing-steel couplers"
PRESET_2023_BARS = "EC2:2023 - straight reinforcing bars"
PRESET_2023_BENT_BARS = "EC2:2023 - bent reinforcing bars"
PRESET_2023_WELDED = "EC2:2023 - tack-welded bars and fabrics"
PRESET_2023_COUPLERS = "EC2:2023 - reinforcing-steel couplers"
PRESET_2005_PRETENSION = "EC2:2005 - pretensioning"
PRESET_2005_PLASTIC_STRAND = "EC2:2005 - strand in plastic duct"
PRESET_2005_PLASTIC_TENDON = "EC2:2005 - tendon in plastic duct"
PRESET_2005_STEEL_CURVED = "EC2:2005 - curved tendon in steel duct"
PRESET_2005_PRESTRESS_COUPLER = "EC2:2005 - prestress coupler"
PRESET_2023_PRETENSION = "EC2:2023 - pretensioning"
PRESET_2023_PLASTIC_STRAND = "EC2:2023 - strand in plastic duct"
PRESET_2023_PLASTIC_TENDON = "EC2:2023 - tendon in plastic duct"
PRESET_2023_STEEL_CURVED = "EC2:2023 - curved tendon in steel duct"
PRESET_2023_PRESTRESS_COUPLER = "EC2:2023 - prestress anchorage/coupler"


def _preset(
    kind: str,
    n_star: float,
    k1: float,
    k2: float,
    delta_sigma: float,
    source: str,
    *,
    stress_model: str = FIXED_STRESS,
    bend_reduction: bool = False,
) -> dict:
    return {
        "kind": kind,
        "n_star": float(n_star),
        "k1": float(k1),
        "k2": float(k2),
        "delta_sigma_rsk_mpa": float(delta_sigma),
        "stress_model": stress_model,
        "bend_reduction": bool(bend_reduction),
        "mandrel_diameter_mm": 0.0,
        "source": source,
    }


DETAIL_PRESETS = {
    PRESET_2005_BARS: _preset(
        MILD, 1e6, 5, 9, 162.5, f"{EC2_2005}, Table 6.3N"
    ),
    PRESET_2005_BENT_BARS: _preset(
        MILD, 1e6, 5, 9, 162.5, f"{EC2_2005}, Table 6.3N, Note 1",
        bend_reduction=True,
    ),
    PRESET_2005_WELDED: _preset(
        MILD, 1e7, 3, 5, 58.5, f"{EC2_2005}, Table 6.3N"
    ),
    PRESET_2005_COUPLERS: _preset(
        MILD, 1e7, 3, 5, 35.0, f"{EC2_2005}, Table 6.3N"
    ),
    PRESET_2023_BARS: _preset(
        MILD, 2e6, 5, 9, 160.0, f"{EC2_2023}, Table E.1",
        stress_model=EC2_2023_BAR_STRESS,
    ),
    PRESET_2023_BENT_BARS: _preset(
        MILD, 2e6, 5, 9, 160.0, f"{EC2_2023}, Table E.1, note a",
        stress_model=EC2_2023_BAR_STRESS, bend_reduction=True,
    ),
    PRESET_2023_WELDED: _preset(
        MILD, 2e6, 3, 5, 100.0, f"{EC2_2023}, Table E.1",
        stress_model=EC2_2023_WELDED_STRESS,
    ),
    PRESET_2023_COUPLERS: _preset(
        MILD, 1e7, 3, 5, 35.0, f"{EC2_2023}, Table E.1"
    ),
    PRESET_2005_PRETENSION: _preset(
        PRESTRESS, 1e6, 5, 9, 185.0, f"{EC2_2005}, Table 6.4N"
    ),
    PRESET_2005_PLASTIC_STRAND: _preset(
        PRESTRESS, 1e6, 5, 9, 185.0, f"{EC2_2005}, Table 6.4N"
    ),
    PRESET_2005_PLASTIC_TENDON: _preset(
        PRESTRESS, 1e6, 5, 10, 150.0, f"{EC2_2005}, Table 6.4N"
    ),
    PRESET_2005_STEEL_CURVED: _preset(
        PRESTRESS, 1e6, 5, 7, 120.0, f"{EC2_2005}, Table 6.4N"
    ),
    PRESET_2005_PRESTRESS_COUPLER: _preset(
        PRESTRESS, 1e6, 5, 5, 80.0, f"{EC2_2005}, Table 6.4N"
    ),
    PRESET_2023_PRETENSION: _preset(
        PRESTRESS, 1e6, 5, 9, 185.0, f"{EC2_2023}, Table E.2"
    ),
    PRESET_2023_PLASTIC_STRAND: _preset(
        PRESTRESS, 1e6, 5, 9, 185.0, f"{EC2_2023}, Table E.2"
    ),
    PRESET_2023_PLASTIC_TENDON: _preset(
        PRESTRESS, 1e6, 5, 9, 150.0, f"{EC2_2023}, Table E.2"
    ),
    PRESET_2023_STEEL_CURVED: _preset(
        PRESTRESS, 1e6, 3, 7, 120.0, f"{EC2_2023}, Table E.2"
    ),
    PRESET_2023_PRESTRESS_COUPLER: _preset(
        PRESTRESS, 1e6, 5, 5, 80.0, f"{EC2_2023}, Table E.2"
    ),
}

DEFAULT_PRESET = PRESET_2005_BARS
CUSTOM_PRESET = "Custom / imported"

DETAIL_FIELDS = (
    "id",
    "name",
    "description",
    "kind",
    "preset",
    "n_star",
    "k1",
    "k2",
    "delta_sigma_rsk_mpa",
    "stress_model",
    "bend_reduction",
    "mandrel_diameter_mm",
    "source",
)

SPECTRUM = "spectrum"
NAME = "name"
DESCRIPTION = "description"
CYCLES = "cycles"
ACTION_COLUMNS = (
    "n_long_ed_kn",
    "mx_long_ed_knm",
    "my_long_ed_knm",
    "n_short_ed_kn",
    "mx_short_ed_knm",
    "my_short_ed_knm",
)
SPECTRUM_COLUMNS = (
    SPECTRUM,
    NAME,
    DESCRIPTION,
    CYCLES,
    *ACTION_COLUMNS,
)
SPECTRUM_TEXT = (SPECTRUM, NAME, DESCRIPTION)
SPECTRUM_NUMERIC = (CYCLES, *ACTION_COLUMNS)


def _kind(value: str) -> str:
    kind = str(value).strip().lower()
    if kind not in KINDS:
        raise ValueError(f"unknown fatigue-detail kind: {value}")
    return kind


def _text(value, fallback: str = "") -> str:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        return fallback
    return str(value).strip()


def _finite(value, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return number if math.isfinite(number) else float(fallback)


def _number(value) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except (TypeError, ValueError):
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _source_items(value) -> list[Mapping]:
    items = value.get("items", []) if isinstance(value, Mapping) else value
    if isinstance(items, Mapping):
        items = [items]
    if not isinstance(items, Iterable) or isinstance(items, (str, bytes)):
        return []
    return [item for item in items if isinstance(item, Mapping)]


def _validate_raw_entry(raw: Mapping, position: int) -> None:
    """Reject explicit malformed engineering fields before applying defaults."""
    label = _text(raw.get("id")) or f"item {position}"
    numeric_fields = (
        "n_star",
        "k1",
        "k2",
        "delta_sigma_rsk_mpa",
        "mandrel_diameter_mm",
    )
    for field in numeric_fields:
        if field not in raw:
            continue
        value = raw[field]
        if isinstance(value, bool):
            raise ValueError(f"{label}: {field} must be a finite number")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{label}: {field} must be a finite number"
            ) from exc
        if not math.isfinite(number):
            raise ValueError(f"{label}: {field} must be a finite number")
    if "kind" in raw and _text(raw["kind"]).lower() not in KINDS:
        raise ValueError(f"{label}: kind must be mild or prestress")
    if (
        "stress_model" in raw
        and _text(raw["stress_model"]) not in STRESS_MODELS
    ):
        raise ValueError(f"{label}: unknown stress_model")
    if "bend_reduction" in raw and not isinstance(raw["bend_reduction"], bool):
        raise ValueError(f"{label}: bend_reduction must be true or false")


def default_entry(
    *,
    detail_id: str = "F1",
    preset: str = DEFAULT_PRESET,
) -> dict:
    values = DETAIL_PRESETS.get(preset, DETAIL_PRESETS[DEFAULT_PRESET])
    return {
        "id": str(detail_id),
        "name": preset.split(" - ", 1)[-1].capitalize(),
        "description": "",
        "preset": preset if preset in DETAIL_PRESETS else DEFAULT_PRESET,
        **copy.deepcopy(values),
    }


def default_catalog() -> dict:
    return {"version": VERSION, "next_id": 2, "items": [default_entry()]}


def _normalise_entry(raw: Mapping, detail_id: str) -> dict:
    selected = _text(raw.get("preset"), DEFAULT_PRESET)
    recognised = selected in DETAIL_PRESETS
    preset = DETAIL_PRESETS.get(selected, DETAIL_PRESETS[DEFAULT_PRESET])
    raw_kind = _text(raw.get("kind"), preset["kind"]).lower()
    kind = raw_kind if raw_kind in KINDS else preset["kind"]
    stress_model = _text(
        raw.get("stress_model"), preset["stress_model"]
    )
    if stress_model not in STRESS_MODELS:
        stress_model = FIXED_STRESS
    out = {
        "id": detail_id,
        "name": _text(raw.get("name")) or detail_id,
        "description": _text(raw.get("description")),
        "kind": kind,
        "preset": selected if recognised else CUSTOM_PRESET,
        "n_star": _finite(raw.get("n_star"), preset["n_star"]),
        "k1": _finite(raw.get("k1"), preset["k1"]),
        "k2": _finite(raw.get("k2"), preset["k2"]),
        "delta_sigma_rsk_mpa": _finite(
            raw.get("delta_sigma_rsk_mpa"),
            preset["delta_sigma_rsk_mpa"],
        ),
        "stress_model": stress_model,
        "bend_reduction": bool(
            raw.get("bend_reduction", preset["bend_reduction"])
        ),
        "mandrel_diameter_mm": _finite(
            raw.get("mandrel_diameter_mm"),
            preset["mandrel_diameter_mm"],
        ),
        "source": _text(raw.get("source"), preset["source"]),
    }
    return out


def normalise_catalog(value) -> dict:
    """Return a canonical catalogue with stable, unique ``F<number>`` IDs."""
    source = _source_items(value)
    if not source:
        return default_catalog()
    for position, raw in enumerate(source, start=1):
        _validate_raw_entry(raw, position)
    pattern = re.compile(r"^F([1-9][0-9]*)$")
    valid_numbers = [
        int(match.group(1))
        for item in source
        if (match := pattern.fullmatch(_text(item.get("id"))))
    ]
    next_number = max(valid_numbers, default=0) + 1
    used: set[str] = set()
    items = []
    for raw in source:
        detail_id = _text(raw.get("id"))
        if not pattern.fullmatch(detail_id) or detail_id in used:
            while f"F{next_number}" in used:
                next_number += 1
            detail_id = f"F{next_number}"
            next_number += 1
        used.add(detail_id)
        items.append(_normalise_entry(raw, detail_id))
    requested_next = value.get("next_id") if isinstance(value, Mapping) else None
    try:
        requested_next = int(requested_next)
    except (TypeError, ValueError):
        requested_next = 1
    next_number = max(next_number, requested_next, 1)
    while f"F{next_number}" in used:
        next_number += 1
    return {"version": VERSION, "next_id": next_number, "items": items}


def entries(catalog) -> list[dict]:
    return normalise_catalog(catalog)["items"]


def entry_map(catalog) -> dict[str, dict]:
    return {item["id"]: item for item in entries(catalog)}


def detail_ids(catalog, kind: str | None = None) -> list[str]:
    selected_kind = _kind(kind) if kind is not None else None
    return [
        item["id"]
        for item in entries(catalog)
        if selected_kind is None or item["kind"] == selected_kind
    ]


def entry_label(entry: Mapping) -> str:
    return f"{entry.get('id', '')} - {entry.get('name', '')}".strip()


def assigned_counts(assigned_ids: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in assigned_ids:
        detail_id = str(value).strip()
        if detail_id:
            counts[detail_id] = counts.get(detail_id, 0) + 1
    return counts


def invalid_assignments(
    assigned_ids: Sequence[str],
    catalog,
    kind: str,
) -> list[str]:
    available = set(detail_ids(catalog, kind))
    return sorted({
        str(value).strip()
        for value in assigned_ids
        if str(value).strip() and str(value).strip() not in available
    })


def _next_id(catalog) -> tuple[dict, str, int]:
    canonical = normalise_catalog(catalog)
    used = set(detail_ids(canonical))
    number = int(canonical["next_id"])
    while f"F{number}" in used:
        number += 1
    return canonical, f"F{number}", number + 1


def add_entry(catalog, *, preset: str = DEFAULT_PRESET) -> tuple[dict, str]:
    canonical, detail_id, next_number = _next_id(catalog)
    canonical["items"].append(default_entry(detail_id=detail_id, preset=preset))
    canonical["next_id"] = next_number
    return canonical, detail_id


def duplicate_entry(catalog, detail_id: str) -> tuple[dict, str]:
    canonical, new_id, next_number = _next_id(catalog)
    source = next(
        (item for item in canonical["items"] if item["id"] == detail_id),
        None,
    )
    if source is None:
        raise KeyError(detail_id)
    item = copy.deepcopy(source)
    item["id"] = new_id
    item["name"] = f"{source['name']} copy"
    canonical["items"].append(item)
    canonical["next_id"] = next_number
    return canonical, new_id


def delete_entry(
    catalog,
    detail_id: str,
    *,
    assigned_ids: Sequence[str] = (),
) -> dict:
    canonical = normalise_catalog(catalog)
    if len(canonical["items"]) <= 1:
        raise ValueError("at least one fatigue detail must remain")
    if detail_id in {str(value).strip() for value in assigned_ids}:
        raise ValueError("fatigue detail is assigned to an element")
    kept = [item for item in canonical["items"] if item["id"] != detail_id]
    if len(kept) == len(canonical["items"]):
        raise KeyError(detail_id)
    canonical["items"] = kept
    return canonical


def replace_entry(catalog, entry: Mapping) -> dict:
    canonical = normalise_catalog(catalog)
    detail_id = _text(entry.get("id"))
    found = False
    items = []
    for item in canonical["items"]:
        if item["id"] == detail_id:
            items.append(_normalise_entry(entry, detail_id))
            found = True
        else:
            items.append(item)
    if not found:
        raise KeyError(detail_id)
    canonical["items"] = items
    return canonical


def apply_preset(entry: Mapping, preset: str) -> dict:
    if preset not in DETAIL_PRESETS:
        raise KeyError(preset)
    out = dict(entry)
    out.update(copy.deepcopy(DETAIL_PRESETS[preset]))
    out["preset"] = preset
    return _normalise_entry(out, _text(out.get("id")))


def catalog_errors(catalog) -> list[str]:
    errors = []
    for item in entries(catalog):
        detail_id = item["id"]
        for field in ("n_star", "k1", "k2", "delta_sigma_rsk_mpa"):
            if not math.isfinite(float(item[field])) or float(item[field]) <= 0.0:
                errors.append(f"{detail_id}: {field} must be greater than zero")
        if (
            item["bend_reduction"]
            and (
                not math.isfinite(float(item["mandrel_diameter_mm"]))
                or float(item["mandrel_diameter_mm"]) <= 0.0
            )
        ):
            errors.append(
                f"{detail_id}: mandrel_diameter_mm must be greater than zero "
                "for a bent-bar detail"
            )
    return errors


def characteristic_stress_range(
    entry: Mapping,
    diameter_mm: float,
) -> float:
    """Return ``delta_sigma_Rsk`` before a possible bent-bar reduction."""
    item = _normalise_entry(entry, _text(entry.get("id"), "F1"))
    diameter = _finite(diameter_mm, math.nan)
    if not math.isfinite(diameter) or diameter <= 0.0:
        raise ValueError("diameter_mm must be greater than zero")
    if item["stress_model"] == EC2_2023_BAR_STRESS:
        if diameter <= 12.0:
            return 160.0
        if diameter <= 16.0:
            return 140.0
        return 130.0
    if item["stress_model"] == EC2_2023_WELDED_STRESS:
        return 100.0 if diameter <= 12.0 else 80.0
    return float(item["delta_sigma_rsk_mpa"])


def bend_reduction_factor(entry: Mapping, diameter_mm: float) -> float:
    """Return the EC2 bent-bar factor, or 1.0 for a straight detail."""
    item = _normalise_entry(entry, _text(entry.get("id"), "F1"))
    if not item["bend_reduction"]:
        return 1.0
    diameter = _finite(diameter_mm, math.nan)
    mandrel = float(item["mandrel_diameter_mm"])
    if not math.isfinite(diameter) or diameter <= 0.0:
        raise ValueError("diameter_mm must be greater than zero")
    if not math.isfinite(mandrel) or mandrel <= 0.0:
        raise ValueError("mandrel_diameter_mm must be greater than zero")
    return min(1.0, 0.35 + 0.026 * mandrel / diameter)


def empty_spectrum_table() -> pd.DataFrame:
    data = {
        column: pd.Series(
            dtype="string" if column in SPECTRUM_TEXT else "float64"
        )
        for column in SPECTRUM_COLUMNS
    }
    frame = pd.DataFrame(data, columns=SPECTRUM_COLUMNS)
    frame.attrs["sector_fatigue_spectrum"] = VERSION
    return frame


def normalise_spectrum_table(value) -> pd.DataFrame:
    if value is None:
        return empty_spectrum_table()
    if (
        isinstance(value, pd.DataFrame)
        and value.attrs.get("sector_fatigue_spectrum") == VERSION
        and tuple(value.columns) == SPECTRUM_COLUMNS
    ):
        return value.copy(deep=True).reset_index(drop=True)
    try:
        frame = (
            value.copy(deep=True)
            if isinstance(value, pd.DataFrame)
            else pd.DataFrame(value)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("fatigue spectrum is not tabular") from exc
    result = pd.DataFrame(index=frame.index)
    for column in SPECTRUM_TEXT:
        source = frame[column] if column in frame else pd.Series("", index=frame.index)
        result[column] = source.map(_text).astype("string")
    for column in SPECTRUM_NUMERIC:
        source = frame[column] if column in frame else pd.Series(0.0, index=frame.index)
        result[column] = source.map(_number).astype("float64")
    result = result.loc[:, SPECTRUM_COLUMNS].reset_index(drop=True)
    result.attrs["sector_fatigue_spectrum"] = VERSION
    return result


def _blank_spectrum_row(row: Mapping) -> bool:
    def finite_zero(value) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(number) and number == 0.0

    return bool(
        not any(_text(row.get(column)) for column in SPECTRUM_TEXT)
        and all(finite_zero(row.get(column)) for column in SPECTRUM_NUMERIC)
    )


def active_spectrum_table(value) -> pd.DataFrame:
    frame = normalise_spectrum_table(value)
    keep = [
        not _blank_spectrum_row(row)
        for row in frame.to_dict("records")
    ]
    return frame.loc[keep].reset_index(drop=True)


def spectrum_records(value) -> list[dict]:
    frame = active_spectrum_table(value)
    records = []
    for row_number, row in enumerate(frame.to_dict("records"), start=1):
        record = {column: _text(row[column]) for column in SPECTRUM_TEXT}
        for column in SPECTRUM_NUMERIC:
            try:
                number = float(row[column])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"fatigue spectrum row {row_number}: {column} must be finite"
                ) from exc
            if not math.isfinite(number):
                raise ValueError(
                    f"fatigue spectrum row {row_number}: {column} must be finite"
                )
            record[column] = number
        records.append(record)
    return records


def spectrum_from_records(records) -> pd.DataFrame:
    if records is None:
        return empty_spectrum_table()
    if (
        not isinstance(records, list)
        or any(not isinstance(row, Mapping) for row in records)
    ):
        raise ValueError("fatigue spectrum is not a list of row objects")
    return normalise_spectrum_table(records)


def spectrum_errors(
    value,
    *,
    existing_case_names: Sequence[str] = (),
    require_rows: bool = False,
) -> list[str]:
    frame = active_spectrum_table(value)
    errors = []
    if require_rows and frame.empty:
        return ["At least one fatigue spectrum bin is required"]
    seen = {
        str(name).strip().casefold()
        for name in existing_case_names
        if str(name).strip()
    }
    spectrum_labels: dict[str, str] = {}
    for index, row in frame.iterrows():
        number = index + 1
        spectrum = _text(row[SPECTRUM])
        name = _text(row[NAME])
        if not spectrum:
            errors.append(f"Fatigue row {number}: Spectrum is required")
        else:
            folded_spectrum = spectrum.casefold()
            prior_label = spectrum_labels.get(folded_spectrum)
            if prior_label is None:
                spectrum_labels[folded_spectrum] = spectrum
            elif prior_label != spectrum:
                errors.append(
                    f"Fatigue row {number}: Spectrum '{spectrum}' differs "
                    f"only by case from '{prior_label}'; use one spelling"
                )
        if not name:
            errors.append(f"Fatigue row {number}: Name is required")
        else:
            folded = name.casefold()
            if folded in seen:
                errors.append(
                    f"Case name '{name}' is duplicated; names must be unique"
                )
            else:
                seen.add(folded)
        cycles = float(row[CYCLES])
        if not math.isfinite(cycles) or cycles <= 0.0:
            errors.append(f"Fatigue row {number}: cycles must be greater than zero")
        for column in ACTION_COLUMNS:
            if not math.isfinite(float(row[column])):
                errors.append(
                    f"Fatigue row {number}: {column} must be a finite number"
                )
    return errors


def spectrum_groups(value) -> dict[str, list[dict]]:
    """Return ordered spectrum groups; each group is assessed independently."""
    grouped: dict[str, list[dict]] = {}
    labels: dict[str, str] = {}
    for record in spectrum_records(value):
        folded = record[SPECTRUM].casefold()
        label = labels.setdefault(folded, record[SPECTRUM])
        grouped.setdefault(label, []).append(record)
    return grouped


def spectrum_signature(value) -> tuple:
    return tuple(
        tuple(record[column] for column in SPECTRUM_COLUMNS)
        for record in spectrum_records(value)
    )


def catalog_signature(catalog) -> tuple:
    return tuple(
        tuple(item[field] for field in DETAIL_FIELDS)
        for item in entries(catalog)
    )
