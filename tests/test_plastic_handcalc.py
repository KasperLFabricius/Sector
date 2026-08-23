"""External-first comparison of Sector with inventoried handcalc outputs.

The PDF ingestion stage imports no Sector calculation package. It emits every
parseable section candidate and a complete source/selection manifest before the
separate production comparison runs. These are external regression comparisons,
not independently derived hand calculations; the retained record reports both
agreements and disagreements instead of filtering the latter out.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from tools import compare_handcalc_fixtures as comparison
from tools import gen_handcalc_fixtures as ingestion


ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "tests" / "handcalc_fixtures.py"
SOURCE_MANIFEST_PATH = (
    ROOT / "tests" / "fixtures" / "handcalc_source_manifest.json"
)
COMPARISON_PATH = ROOT / "tests" / "fixtures" / "handcalc_comparison.json"
GENERATOR_PATH = ROOT / "tools" / "gen_handcalc_fixtures.py"

CASES = comparison.load_cases(FIXTURE_PATH)
SOURCE_MANIFEST = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
RETAINED_COMPARISON = json.loads(COMPARISON_PATH.read_text(encoding="utf-8"))
RETAINED_BY_CASE = {
    case["name"]: case for case in RETAINED_COMPARISON["cases"]
}


def test_external_fixture_inventory_is_complete_and_traceable():
    summary = SOURCE_MANIFEST["summary"]
    assert SOURCE_MANIFEST["selection_policy"] == {
        "production_imports": False,
        "production_result_filter": False,
        "row_selection": (
            "all rows when at most four exist; otherwise deterministic "
            "indices range(0, count, count // 4 + 1)"
        ),
    }
    assert summary["source_files"] == 18
    assert summary["selected_source_files"] == 18
    assert summary["rejected_source_files"] == 0
    assert summary["discovered_blocks"] == 29
    assert summary["selected_blocks"] == len(CASES) == 29
    assert summary["rejected_blocks"] == 0
    assert summary["available_result_rows"] == 1365
    assert summary["selected_result_rows"] == sum(
        len(case["rows"]) for case in CASES
    ) == 99

    selected_blocks = {
        block["case_name"]: (source, block)
        for source in SOURCE_MANIFEST["sources"]
        for block in source["blocks"]
        if block["status"] == "selected"
    }
    assert set(selected_blocks) == {case["name"] for case in CASES}
    for source in SOURCE_MANIFEST["sources"]:
        assert len(source["sha256"]) == 64
        assert source["status"] in {"selected", "rejected"}
        if source["status"] == "rejected":
            assert source["reason"]
        for block in source["blocks"]:
            assert block["status"] in {"selected", "rejected"}
            if block["status"] == "rejected":
                assert block["reason"]

    for case in CASES:
        source, block = selected_blocks[case["name"]]
        assert case["source_id"] == source["source_id"]
        assert case["source_sha256"] == source["sha256"]
        assert case["source_block"] == block["block_index"]
        assert case["available_result_rows"] == block["available_result_rows"]
        assert list(case["selected_row_indices"]) == block["selected_row_indices"]


def test_external_generator_has_no_sector_import_or_local_absolute_default():
    source = GENERATOR_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    production_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (
            node.module == "sector" or str(node.module).startswith("sector.")
        ):
            production_imports.append(node.module)
        elif isinstance(node, ast.Import):
            production_imports.extend(
                alias.name
                for alias in node.names
                if alias.name == "sector" or alias.name.startswith("sector.")
            )
    assert production_imports == []
    assert "case_matches" not in source
    assert "C:\\Users\\" not in source


def test_retained_comparison_identifies_the_exact_external_inputs():
    assert (
        RETAINED_COMPARISON["fixture_sha256"]
        == comparison.sha256_canonical_text(FIXTURE_PATH)
    )
    assert (
        RETAINED_COMPARISON["source_manifest_sha256"]
        == comparison.sha256_canonical_text(SOURCE_MANIFEST_PATH)
    )
    summary = RETAINED_COMPARISON["summary"]
    assert summary["candidate_cases"] == len(CASES) == 29
    assert summary["candidate_rows"] == 99
    assert summary["rows_within_tolerance"] == 95
    assert summary["complete_agreement_cases"] == 27
    assert summary["row_agreement_rate"] == pytest.approx(95 / 99)
    assert set(RETAINED_BY_CASE) == {case["name"] for case in CASES}


def test_legacy_annulus_fixtures_are_mapped_to_two_valid_rings():
    annulus_cases = [case for case in CASES if len(case["corners"]) == 74]
    assert len(annulus_cases) == 8
    for case in annulus_cases:
        outer, holes = comparison.rings(case)
        assert len(outer) == 37
        assert len(holes) == 1 and len(holes[0]) == 37
        section, _concrete, _mild, _prestress = comparison.build_case(case)
        assert len(section.concrete) == 2


def test_external_ingestion_rejection_has_an_explicit_reason():
    fixture, outcome = ingestion.parse_block(
        ["CONCRETE: 4 CORNERS", "no reinforcement material definition"]
    )

    assert fixture is None
    assert outcome["status"] == "rejected"
    assert outcome["reason"] == "reinforcement_material_definition_not_found"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_handcalc_external_candidate_does_not_regress(case):
    retained = RETAINED_BY_CASE[case["name"]]
    current = comparison.compare_case(case)

    assert current["summary"]["rows"] == retained["summary"]["rows"]
    assert current["summary"]["reason"] is None
    assert len(current["rows"]) == len(retained["rows"])
    for current_row, retained_row in zip(current["rows"], retained["rows"]):
        assert current_row["source_row_index"] == retained_row["source_row_index"]
        if retained_row["within_tolerance"]:
            assert current_row["within_tolerance"], (
                f"{case['name']} source row {current_row['source_row_index']} "
                "regressed outside the retained external-comparison tolerance"
            )
            continue

        assert current_row["actual"] is not None
        retained_worst = max(
            metric["normalised_error"]
            for metric in retained_row["metrics"].values()
        )
        current_worst = max(
            metric["normalised_error"]
            for metric in current_row["metrics"].values()
        )
        assert current_worst <= retained_worst * 1.001 + 1.0e-6


def test_complete_external_agreement_rate_is_reported_and_not_reduced():
    current = comparison.build_comparison(
        CASES,
        fixture_path=FIXTURE_PATH,
        source_manifest_path=SOURCE_MANIFEST_PATH,
    )
    retained = RETAINED_COMPARISON["summary"]
    summary = current["summary"]

    assert summary["candidate_cases"] == retained["candidate_cases"]
    assert summary["candidate_rows"] == retained["candidate_rows"]
    assert summary["rows_within_tolerance"] >= retained["rows_within_tolerance"]
    assert summary["row_agreement_rate"] >= retained["row_agreement_rate"]


def test_comparison_negative_control_retains_a_disagreement():
    mutated = copy.deepcopy(CASES[0])
    row = list(mutated["rows"][0])
    row[2] += 10.0 * max(abs(row[2]), abs(row[3]), 1.0)
    mutated["rows"][0] = tuple(row)

    record = comparison.compare_case(mutated)
    assert not record["rows"][0]["within_tolerance"]
    assert record["rows"][0]["reason"] == (
        "one_or_more_metrics_outside_tolerance"
    )
