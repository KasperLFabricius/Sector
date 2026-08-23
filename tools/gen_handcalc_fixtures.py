"""Ingest external hand-calculation PDFs without importing Sector calculations.

The first pipeline stage inventories every PDF, retains its SHA-256, records
every block parse/selection outcome, and emits deterministic external
expectations. It deliberately performs no Sector solve and cannot select a case
because Sector agrees with it. Run ``tools/compare_handcalc_fixtures.py``
afterwards to create the separate production-comparison record.

Usage::

    python tools/gen_handcalc_fixtures.py PDF_DIR

``PDF_DIR`` may instead be supplied through ``HANDCALC_DIR``. There is no
machine-specific default. Raw PDF text is never printed or committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE_PATH = ROOT / "tests" / "handcalc_fixtures.py"
DEFAULT_MANIFEST_PATH = (
    ROOT / "tests" / "fixtures" / "handcalc_source_manifest.json"
)

# The source files were renamed after the original fixtures were issued. These
# basename-only aliases retain the established case identities without storing
# a user-specific path or consulting a Sector result.
SOURCE_ID_OVERRIDES = {
    "Bro 337-0-010.00 - Pcross.pdf": "Bro_337_0_010.00__",
    "Pcross output example.pdf": "handcalc_example",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ascii_text(path: Path) -> str:
    reader = PdfReader(path)
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return "".join(
        character if ord(character) < 128 else " " for character in text
    )


def nums(line: str) -> list[float]:
    return [
        float(value.replace("D", "E"))
        for value in re.findall(
            r"[-+]?\d*\.?\d+(?:[DE][-+]?\d+)?", line
        )
    ]


def clean_name(path: Path) -> str:
    if path.name in SOURCE_ID_OVERRIDES:
        return SOURCE_ID_OVERRIDES[path.name]
    name = "".join(
        character if ord(character) < 128 else "_"
        for character in path.name
    )
    return (
        name.replace(".pcr.pdf", "")
        .replace(".pdf", "")
        .replace(" ", "_")
        .replace("-", "_")
    )


def result_rows(lines: list[str], has_cable: bool):
    current_axial = None
    pending = False
    for line in lines:
        if "LOAD CASE" in line:
            pending = True
            continue
        if (
            pending
            and re.search(r"\d", line)
            and "V.MIN" not in line
            and "P " not in line[:3]
        ):
            values = nums(line)
            if values:
                current_axial, pending = values[0], False
            continue
        if current_axial is not None and re.search(r"\dD[-+]\d", line):
            values = nums(line)
            if len(values) >= 11:
                yield current_axial, has_cable, values


def strain_cols(
    has_steel: bool,
    has_cable: bool,
    values: list[float],
) -> tuple[float, float, float | None, float]:
    """Return concrete, steel, cable and curvature source columns."""

    concrete, index = values[7], 8
    steel = values[index] if has_steel else 0.0
    if has_steel:
        index += 1
    cable = values[index] if has_cable else None
    if has_cable:
        index += 1
    return concrete, steel, cable, values[index]


def selected_row_indices(count: int) -> tuple[int, ...]:
    """Return a deterministic, production-independent angular sample."""

    if count <= 4:
        return tuple(range(count))
    step = count // 4 + 1
    return tuple(range(0, count, step))


def _find(blob: str, pattern: str, default: str | None = None) -> str | None:
    match = re.search(pattern, blob, re.DOTALL)
    return match.group(1) if match else default


def parse_block(lines: list[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Parse one external section block into plain data and an outcome record."""

    blob = "\n".join(lines)
    outcome: dict[str, Any] = {
        "status": "rejected",
        "reason": None,
        "warnings": [],
        "available_result_rows": 0,
        "selected_row_indices": [],
    }
    if "MILD STEEL" not in blob and "PRESTRESSED STEEL:" not in blob:
        outcome["reason"] = "reinforcement_material_definition_not_found"
        return None, outcome

    declared_corners = int(
        _find(blob, r"CONCRETE:\s+(\d+)\s+CORNERS", "0") or "0"
    )
    concrete = {
        "fck": float(
            _find(blob, r"COMPRESSION STRENGTH\s+([\d.]+)", "30") or "30"
        ),
        "gamma_c": float(
            _find(blob, r"SAFETY FACTOR FOR CONCRETE\s+([\d.]+)", "1.5")
            or "1.5"
        ),
        "curve": int(
            _find(blob, r"CONCRETE:.*?\(type\s+(\d+)\)", "1") or "1"
        ),
    }

    fytk = float(
        _find(
            blob,
            r"MILD STEEL.*?YIELD STRESS, TENSION\s+([\d.]+)",
            "500",
        )
        or "500"
    )
    gamma_y = float(
        _find(blob, r"SAFETY FACTOR FOR MILD STEEL\s+([\d.]+)", "1")
        or "1"
    )
    mild = {
        "fytk": fytk,
        "fyck": float(
            _find(
                blob,
                r"MILD STEEL.*?YIELD STRESS, COMPRESSION\s+([\d.]+)",
                str(fytk),
            )
            or str(fytk)
        ),
        "eut": round(
            float(
                _find(
                    blob,
                    r"MILD STEEL.*?RUPTURE ELONGATION, TENSION\s+([\d.]+)",
                    "5",
                )
                or "5"
            )
            / 100.0,
            4,
        ),
        "futk": float(
            _find(
                blob,
                r"MILD STEEL.*?RUPTURE STRESS, TENSION\s+([\d.]+)",
                str(fytk),
            )
            or str(fytk)
        ),
        "gamma_y": gamma_y,
        "gamma_u": float(
            _find(
                blob,
                r"RUPTURE TENSILE STRESS FOR MILD STEEL\s+([\d.]+)",
                str(gamma_y),
            )
            or str(gamma_y)
        ),
        "gamma_E": float(
            _find(
                blob,
                r"E-MODULUS FOR MILD STEEL\s+([\d.]+)",
                str(gamma_y),
            )
            or str(gamma_y)
        ),
        "curve": int(
            _find(
                blob,
                r"MILD STEEL\s+\d+\s+BARS\s+\(type\s+(\d+)\)",
                "1",
            )
            or "1"
        ),
    }

    prestress = None
    if "PRESTRESSED STEEL:" in blob:
        curve = int(
            _find(
                blob,
                r"PRESTRESSED STEEL:.*?\(type\s+(\d+)\)",
                "1",
            )
            or "1"
        )
        prestress = {
            "curve": curve,
            "IS": round(
                float(
                    _find(blob, r"INITIAL STRAIN\s+([\d.]+)", "0") or "0"
                )
                / 100.0,
                5,
            ),
            "gamma_y": float(
                _find(
                    blob,
                    r"SAFETY FACTOR FOR PRESTRESSED STEEL\s+([\d.]+)",
                    "1",
                )
                or "1"
            ),
            "gamma_u": 1.0,
            "gamma_E": 1.0,
            "fytk": 0.0,
            "futk": 0.0,
            "eut": 0.035,
        }
        if curve in (6, 7):
            prestress.update(
                {
                    "fytk": float(
                        _find(
                            blob,
                            r"PRESTRESSED STEEL:.*?YIELD STRESS, TENSION\s+([\d.]+)",
                            "1600",
                        )
                        or "1600"
                    ),
                    "futk": float(
                        _find(
                            blob,
                            r"PRESTRESSED STEEL:.*?RUPTURE STRESS, TENSION\s+([\d.]+)",
                            "1800",
                        )
                        or "1800"
                    ),
                    "eut": round(
                        float(
                            _find(
                                blob,
                                r"PRESTRESSED STEEL:.*?RUPTURE ELONGATION, TENSION\s+([\d.]+)",
                                "3.5",
                            )
                            or "3.5"
                        )
                        / 100.0,
                        4,
                    ),
                    "gamma_u": float(
                        _find(
                            blob,
                            r"RUPTURE TENSILE STRESS FOR PRESTRESSED STEEL\s+([\d.]+)",
                            "1.1",
                        )
                        or "1.1"
                    ),
                    "gamma_E": float(
                        _find(
                            blob,
                            r"E-MODULUS FOR PRESTRESSED STEEL\s+([\d.]+)",
                            "1",
                        )
                        or "1"
                    ),
                }
            )

    declared_bars = int(
        _find(blob, r"MILD STEEL\s+(\d+)\s+BARS", "0") or "0"
    )
    declared_tendons = int(
        _find(blob, r"PRESTRESSED STEEL:\s+(\d+)\s+CABLES", "0") or "0"
    )
    corners: list[tuple[float, float]] = []
    bars: list[tuple[float, float, float]] = []
    tendons: list[tuple[float, float, float]] = []
    in_table = False
    for line in lines:
        if "ABSCISSA" in line and "ORDINATE" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if "LOAD CASE" in line:
            break
        values = nums(line)
        if not values:
            continue
        remaining = values[1:]
        if "MILD STEEL" in line or "PRESTRESSED STEEL" in line:
            if len(remaining) >= 5:
                if len(corners) < declared_corners:
                    corners.append((remaining[0], remaining[1]))
                bar_x, bar_y, area = remaining[2], remaining[3], remaining[4]
            elif len(remaining) >= 3:
                bar_x, bar_y, area = remaining[0], remaining[1], remaining[2]
            else:
                continue
            if "PRESTRESSED STEEL" in line:
                if len(tendons) < declared_tendons:
                    tendons.append((bar_x, bar_y, area))
            elif len(bars) < declared_bars:
                bars.append((bar_x, bar_y, area))
        elif len(remaining) >= 2 and len(corners) < declared_corners:
            corners.append((remaining[0], remaining[1]))

    outcome["declared_counts"] = {
        "corners": declared_corners,
        "bars": declared_bars,
        "tendons": declared_tendons,
    }
    outcome["parsed_counts"] = {
        "corners": len(corners),
        "bars": len(bars),
        "tendons": len(tendons),
    }
    if len(corners) < 3:
        outcome["reason"] = "fewer_than_three_concrete_points"
        return None, outcome
    for label, declared, parsed in (
        ("corners", declared_corners, len(corners)),
        ("bars", declared_bars, len(bars)),
        ("tendons", declared_tendons, len(tendons)),
    ):
        if declared != parsed:
            outcome["warnings"].append(
                f"declared_{label}_{declared}_parsed_{parsed}"
            )

    rows = list(result_rows(lines, prestress is not None))
    indices = selected_row_indices(len(rows))
    outcome["available_result_rows"] = len(rows)
    outcome["selected_row_indices"] = list(indices)
    if not rows:
        outcome["reason"] = "no_result_rows"
        return None, outcome

    expected_rows = []
    for index in indices:
        current_axial, _has_cable, values = rows[index]
        concrete_strain, steel_strain, cable_strain, curvature = strain_cols(
            bool(bars), prestress is not None, values
        )
        expected_rows.append(
            (
                round(current_axial, 2),
                round(values[4], 1),
                round(values[2], 1),
                round(values[3], 1),
                round(concrete_strain, 2),
                round(steel_strain, 2),
                None if cable_strain is None else round(cable_strain, 2),
                round(curvature, 6),
            )
        )

    fixture = {
        "corners": [(round(x, 4), round(y, 4)) for x, y in corners],
        "bars": [
            (round(x, 4), round(y, 4), round(area, 2))
            for x, y, area in bars
        ],
        "tendons": [
            (round(x, 4), round(y, 4), round(area, 2))
            for x, y, area in tendons
        ],
        "concrete": concrete,
        "mild": mild,
        "prestress": prestress,
        "rows": expected_rows,
    }
    outcome["status"] = "selected"
    return fixture, outcome


def parse_source(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_hash = sha256_file(path)
    source_id = clean_name(path)
    source_record: dict[str, Any] = {
        "source_name": path.name,
        "source_id": source_id,
        "sha256": source_hash,
        "size_bytes": path.stat().st_size,
        "status": "rejected",
        "reason": None,
        "blocks": [],
    }
    try:
        lines = ascii_text(path).splitlines()
    except Exception as exc:
        source_record["reason"] = f"pdf_parse_error:{type(exc).__name__}"
        return source_record, []

    starts = [
        index
        for index, line in enumerate(lines)
        if re.search(r"CONCRETE:\s+\d+\s+CORNERS", line)
    ]
    if not starts:
        source_record["reason"] = "no_section_headers"
        return source_record, []

    fixtures = []
    for block_index, start in enumerate(starts, start=1):
        end = starts[block_index] if block_index < len(starts) else len(lines)
        fixture, outcome = parse_block(lines[start:end])
        case_name = (
            source_id if len(starts) == 1 else f"{source_id}_s{block_index}"
        )
        outcome["block_index"] = block_index
        outcome["case_name"] = case_name
        source_record["blocks"].append(outcome)
        if fixture is None:
            continue
        fixtures.append(
            {
                "name": case_name,
                "source_id": source_id,
                "source_sha256": source_hash,
                "source_block": block_index,
                "available_result_rows": outcome["available_result_rows"],
                "selected_row_indices": tuple(outcome["selected_row_indices"]),
                **fixture,
            }
        )

    if fixtures:
        source_record["status"] = "selected"
    else:
        source_record["reason"] = "no_selectable_blocks"
    return source_record, fixtures


def build_external_dataset(
    pdf_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths = sorted(pdf_dir.glob("*.pdf"), key=lambda path: path.name.casefold())
    if not paths:
        raise ValueError(f"no PDF files found in {pdf_dir}")

    sources = []
    fixtures = []
    for path in paths:
        source, cases = parse_source(path)
        sources.append(source)
        fixtures.extend(cases)

    names = [case["name"] for case in fixtures]
    if len(names) != len(set(names)):
        raise ValueError("external case identities are not unique")

    blocks = [block for source in sources for block in source["blocks"]]
    summary = {
        "source_files": len(sources),
        "selected_source_files": sum(
            source["status"] == "selected" for source in sources
        ),
        "rejected_source_files": sum(
            source["status"] != "selected" for source in sources
        ),
        "discovered_blocks": len(blocks),
        "selected_blocks": sum(block["status"] == "selected" for block in blocks),
        "rejected_blocks": sum(block["status"] != "selected" for block in blocks),
        "available_result_rows": sum(
            block["available_result_rows"] for block in blocks
        ),
        "selected_result_rows": sum(
            len(block["selected_row_indices"]) for block in blocks
        ),
    }
    manifest = {
        "schema_version": 1,
        "generated_by": "tools/gen_handcalc_fixtures.py",
        "selection_policy": {
            "production_imports": False,
            "production_result_filter": False,
            "row_selection": (
                "all rows when at most four exist; otherwise deterministic "
                "indices range(0, count, count // 4 + 1)"
            ),
        },
        "summary": summary,
        "sources": sources,
    }
    return fixtures, manifest


def render_fixture_module(fixtures: list[dict[str, Any]]) -> str:
    lines = [
        '"""External-first fixtures parsed from inventoried handcalc PDFs.',
        "",
        "Every independently parseable block is emitted before Sector comparison.",
        "Source identities and all parse/selection outcomes are retained in",
        "tests/fixtures/handcalc_source_manifest.json.",
        'Regenerate with tools/gen_handcalc_fixtures.py; do not edit by hand.\n"""',
        "",
        "CASES = [",
    ]
    keys = (
        "name",
        "source_id",
        "source_sha256",
        "source_block",
        "available_result_rows",
        "selected_row_indices",
        "corners",
        "bars",
        "tendons",
        "concrete",
        "mild",
        "prestress",
        "rows",
    )
    for fixture in fixtures:
        lines.append("    {")
        for key in keys:
            lines.append(f"        {key!r}: {fixture[key]!r},")
        lines.append("    },")
    lines.append("]")
    text = "\n".join(lines) + "\n"
    if not text.isascii():
        raise ValueError("generated fixture module must remain ASCII")
    return text


def write_external_dataset(
    fixtures: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> None:
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(
        render_fixture_module(fixtures), encoding="utf-8", newline="\n"
    )
    manifest_path.write_text(
        json.dumps(
            manifest,
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
    parser.add_argument(
        "pdf_dir",
        nargs="?",
        default=os.environ.get("HANDCALC_DIR"),
        help="directory containing the external PDF outputs",
    )
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURE_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args(argv)
    if not args.pdf_dir:
        parser.error("PDF_DIR or HANDCALC_DIR is required")

    fixtures, manifest = build_external_dataset(Path(args.pdf_dir))
    write_external_dataset(
        fixtures,
        manifest,
        fixture_path=args.fixtures,
        manifest_path=args.manifest,
    )
    summary = manifest["summary"]
    print(
        "EMITTED",
        summary["selected_blocks"],
        "cases from",
        summary["source_files"],
        "sources; selected rows",
        summary["selected_result_rows"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
