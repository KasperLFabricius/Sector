"""Compare the external-first handcalc fixtures with the Sector plastic solver.

This second pipeline stage is intentionally separate from PDF ingestion. It
records every selected external candidate, including disagreements, and reports
the complete row agreement rate. It never edits or filters the external fixture
set produced by ``gen_handcalc_fixtures.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sector.materials import Concrete, MildSteel, Prestress  # noqa: E402
from sector.plastic import plastic_capacity_at_angle  # noqa: E402
from sector.section import Section  # noqa: E402


DEFAULT_FIXTURE_PATH = ROOT / "tests" / "handcalc_fixtures.py"
DEFAULT_SOURCE_MANIFEST_PATH = (
    ROOT / "tests" / "fixtures" / "handcalc_source_manifest.json"
)
DEFAULT_COMPARISON_PATH = (
    ROOT / "tests" / "fixtures" / "handcalc_comparison.json"
)

TOLERANCES = {
    "moment_relative": 0.03,
    "moment_absolute_knm": 1.0,
    "concrete_strain_absolute_percent": 0.03,
    "steel_strain_absolute_percent": 0.08,
    "cable_strain_absolute_percent": 0.08,
    "curvature_relative": 0.05,
    "curvature_absolute_per_m": 0.0001,
}


def sha256_canonical_text(path: Path) -> str:
    """Hash UTF-8 text with repository LF semantics on every platform."""

    text = path.read_text(encoding="utf-8")
    canonical = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_cases(path: Path = DEFAULT_FIXTURE_PATH) -> list[dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("handcalc_fixtures", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load fixture module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.CASES)


def rings(case: dict[str, Any]):
    """Map a legacy concatenated annulus into outer and hole rings."""

    corners = case["corners"]
    for index in range(2, len(corners) - 2):
        if corners[index] == corners[0]:
            possible_hole = corners[index + 1:]
            if possible_hole and possible_hole[-1] == possible_hole[0]:
                return corners[:index + 1], [possible_hole]
    return corners, []


def build_case(case: dict[str, Any]):
    corners, holes = rings(case)
    section = Section.from_polygon(
        corners=corners,
        holes=holes,
        bars_xy_area_mm2=case["bars"],
        tendons_xy_area_mm2=case["tendons"],
    )
    concrete = Concrete(**case["concrete"])
    mild = MildSteel(**case["mild"])
    prestress = (
        None
        if case["prestress"] is None
        else Prestress(**case["prestress"])
    )
    return section, concrete, mild, prestress


def _number(value: float | None, digits: int = 10) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _metric(expected: float, actual: float, limit: float) -> dict[str, Any]:
    error = abs(float(actual) - float(expected))
    ratio = error / limit if limit > 0.0 else math.inf
    return {
        "absolute_error": _number(error),
        "limit": _number(limit),
        "normalised_error": _number(ratio),
        "within_tolerance": bool(error <= limit),
    }


def compare_row(
    section,
    concrete,
    mild,
    prestress,
    expected_row,
    *,
    row_index: int,
    source_row_index: int,
) -> dict[str, Any]:
    axial, angle, expected_mx, expected_my, expected_ec, expected_es, expected_ep, expected_curvature = expected_row
    expected = {
        "axial_kn": axial,
        "angle_deg": angle,
        "mx_knm": expected_mx,
        "my_knm": expected_my,
        "concrete_strain_percent": expected_ec,
        "steel_strain_percent": expected_es,
        "cable_strain_percent": expected_ep,
        "curvature_per_m": expected_curvature,
    }
    record: dict[str, Any] = {
        "row_index": row_index,
        "source_row_index": source_row_index,
        "expected": expected,
        "actual": None,
        "metrics": {},
        "within_tolerance": False,
        "reason": None,
    }
    try:
        result = plastic_capacity_at_angle(
            section,
            concrete,
            mild,
            axial,
            angle,
            prestress=prestress,
            n_bands=50,
        )
    except Exception as exc:
        record["reason"] = f"solver_exception:{type(exc).__name__}"
        return record

    actual = {
        "converged": bool(result.converged),
        "mx_knm": _number(result.Mx),
        "my_knm": _number(result.My),
        "concrete_strain_percent": _number(result.eps_concrete),
        "steel_strain_percent": _number(result.eps_steel),
        "cable_strain_percent": _number(result.eps_cable),
        "curvature_per_m": _number(result.curvature),
    }
    record["actual"] = actual
    if not result.converged:
        record["reason"] = "solver_not_converged"
        return record

    scale = max(abs(expected_mx), abs(expected_my), 1.0)
    metrics = {
        "mx": _metric(
            expected_mx,
            result.Mx,
            TOLERANCES["moment_relative"] * scale
            + TOLERANCES["moment_absolute_knm"],
        ),
        "my": _metric(
            expected_my,
            result.My,
            TOLERANCES["moment_relative"] * scale
            + TOLERANCES["moment_absolute_knm"],
        ),
        "concrete_strain": _metric(
            expected_ec,
            result.eps_concrete,
            TOLERANCES["concrete_strain_absolute_percent"],
        ),
        "steel_strain": _metric(
            expected_es,
            result.eps_steel,
            TOLERANCES["steel_strain_absolute_percent"],
        ),
        "curvature": _metric(
            expected_curvature,
            result.curvature,
            TOLERANCES["curvature_relative"] * abs(expected_curvature)
            + TOLERANCES["curvature_absolute_per_m"],
        ),
    }
    if expected_ep is not None:
        metrics["cable_strain"] = _metric(
            expected_ep,
            result.eps_cable,
            TOLERANCES["cable_strain_absolute_percent"],
        )
    record["metrics"] = metrics
    record["within_tolerance"] = all(
        metric["within_tolerance"] for metric in metrics.values()
    )
    if not record["within_tolerance"]:
        record["reason"] = "one_or_more_metrics_outside_tolerance"
    return record


def compare_case(case: dict[str, Any]) -> dict[str, Any]:
    case_record: dict[str, Any] = {
        "name": case["name"],
        "source_id": case["source_id"],
        "source_sha256": case["source_sha256"],
        "source_block": case["source_block"],
        "rows": [],
        "summary": None,
    }
    try:
        section, concrete, mild, prestress = build_case(case)
    except Exception as exc:
        case_record["summary"] = {
            "rows": len(case["rows"]),
            "rows_within_tolerance": 0,
            "complete_agreement": False,
            "reason": f"case_build_error:{type(exc).__name__}",
        }
        return case_record

    source_indices = case["selected_row_indices"]
    rows = [
        compare_row(
            section,
            concrete,
            mild,
            prestress,
            expected,
            row_index=index,
            source_row_index=source_indices[index],
        )
        for index, expected in enumerate(case["rows"])
    ]
    agreeing = sum(row["within_tolerance"] for row in rows)
    case_record["rows"] = rows
    case_record["summary"] = {
        "rows": len(rows),
        "rows_within_tolerance": agreeing,
        "complete_agreement": agreeing == len(rows),
        "reason": None,
    }
    return case_record


def build_comparison(
    cases: list[dict[str, Any]],
    *,
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
    source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST_PATH,
) -> dict[str, Any]:
    records = [compare_case(case) for case in cases]
    total_rows = sum(record["summary"]["rows"] for record in records)
    agreeing_rows = sum(
        record["summary"]["rows_within_tolerance"] for record in records
    )
    complete_cases = sum(
        record["summary"]["complete_agreement"] for record in records
    )
    return {
        "schema_version": 1,
        "generated_by": "tools/compare_handcalc_fixtures.py",
        "fixture_sha256": sha256_canonical_text(fixture_path),
        "source_manifest_sha256": sha256_canonical_text(source_manifest_path),
        "tolerances": TOLERANCES,
        "summary": {
            "candidate_cases": len(records),
            "complete_agreement_cases": complete_cases,
            "candidate_rows": total_rows,
            "rows_within_tolerance": agreeing_rows,
            "row_agreement_rate": (
                round(agreeing_rows / total_rows, 8) if total_rows else 0.0
            ),
        },
        "cases": records,
    }


def write_comparison(
    comparison: dict[str, Any],
    path: Path = DEFAULT_COMPARISON_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            comparison,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURE_PATH)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=DEFAULT_SOURCE_MANIFEST_PATH,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_COMPARISON_PATH)
    parser.add_argument("--require-complete-agreement", action="store_true")
    args = parser.parse_args(argv)

    cases = load_cases(args.fixtures)
    comparison = build_comparison(
        cases,
        fixture_path=args.fixtures,
        source_manifest_path=args.source_manifest,
    )
    write_comparison(comparison, args.output)
    summary = comparison["summary"]
    print(
        "COMPARED",
        summary["candidate_rows"],
        "rows; within tolerance",
        summary["rows_within_tolerance"],
        "rate",
        f"{summary['row_agreement_rate']:.6f}",
    )
    if (
        args.require_complete_agreement
        and summary["rows_within_tolerance"] != summary["candidate_rows"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
