"""Characteristic-strength comparisons for existing elastic stress outputs.

These ratios describe displayed stresses. They are not acceptance criteria and
do not select a governing result or infer a missing characteristic strength.
"""

from collections.abc import Mapping
import math
from numbers import Real


COMPONENTS = (
    ("total_mpa", "Total"),
    ("long_mpa", "Long-term"),
    ("dif_mpa", "Short-term increment"),
    ("rst1_mpa", "Instantaneous response"),
)


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def percentage(stress, strength):
    """Compare stress magnitude; reject absent, nonfinite or nonpositive strengths."""
    stress, strength = finite_number(stress), finite_number(strength)
    if stress is None or strength is None or strength <= 0.0:
        return None
    result = abs(stress) / strength * 100.0
    return result if math.isfinite(result) else None


def element_references(inp, row):
    """Resolve only the law assigned to this exact element and material ID."""
    tendon = row.get("element_type") == "Tendon"
    labels = ("f_pk", "f_p0.1k") if tendon else ("f_yk",)
    missing = dict.fromkeys(labels)
    if not row.get("element_id") or row.get("element_type") not in {"Bar", "Tendon"}:
        return missing
    prefix = "tendon" if tendon else "bar"
    elements = inp.get(f"{prefix}_elements") or ()
    materials = inp.get(f"{prefix}_materials") or ()
    if len(elements) != len(materials):
        return missing
    matched = [
        (element, material) for element, material in zip(elements, materials)
        if isinstance(element, Mapping)
        and element.get("id") == row.get("element_id")
    ]
    if len(matched) != 1:
        return missing
    element, material = matched[0]
    if not row.get("material_id") or element.get("material_id") != row["material_id"]:
        return missing
    if tendon:
        # Fixed curves 1-5 have no declared f_pk/f_p0.1k law fields. Their
        # dataclass defaults and rupture ordinates are not these references.
        if getattr(material, "curve", None) not in (6, 7):
            return missing
        return {"f_pk": getattr(material, "futk", None),
                "f_p0.1k": getattr(material, "fytk", None)}
    return {"f_yk": getattr(material, "fytk", None)}


def output_references(inp, elastic, key, output):
    """Use the already selected output identity, never choose another element."""
    if key == "concrete":
        return {"f_ck": getattr(inp.get("concrete"), "fck", None)}
    tendon = key == "prestress"
    missing = dict.fromkeys(("f_pk", "f_p0.1k") if tendon else ("f_yk",))
    expected_type = "Tendon" if tendon else "Bar"
    rows = [row for row in (elastic.get("elements") or ())
            if isinstance(row, Mapping)
            and row.get("element_type") == expected_type
            and row.get("element_id") == output.get("governing")]
    if len(rows) != 1:
        return missing
    return element_references(inp, rows[0])


def comparison_text(stress, references):
    parts = []
    for label, strength in references.items():
        ratio = percentage(stress, strength)
        parts.append(f"{label}: unavailable" if ratio is None
                     else f"{ratio:.1f}% of {label}")
    return "; ".join(parts)


def output_comparison(inp, elastic, key, output):
    return comparison_text(output.get("value"),
                           output_references(inp, elastic, key, output))


def element_comparison_rows(inp, elements):
    """One compact comparison row per element and characteristic reference."""
    rows = []
    for element in elements:
        for reference, strength in element_references(inp, element).items():
            rows.append({
                "Element": element.get("element_id") or "-",
                "Material": element.get("material_id") or "-",
                "Reference": reference,
                **{label: percentage(element.get(key), strength)
                   for key, label in COMPONENTS},
            })
    return rows
