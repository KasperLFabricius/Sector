import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAMME = ROOT / "docs" / "v094_pr_programme.md"
DECISIONS = ROOT / "docs" / "v094_decision_register.md"
FIXTURE = ROOT / "tests" / "fixtures" / "v094_review_cases.json"
BASE = "c1086a2cb8b20a8339ae72bf30218b0b8c6c4dfe"
TREE = "1ac7905eb5e6fd48cce50def16f769a7e8458be0"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_programme_freezes_exact_base_and_fourteen_ordered_slices() -> None:
    text = _text(PROGRAMME)
    assert BASE in text
    assert TREE in text

    rows = re.findall(r"^\| (\d+) \| PR-(\d+) - ", text, flags=re.MULTILINE)
    assert rows == [(str(i), f"{i:02d}") for i in range(1, 15)]
    assert "PR-14 first runs the complete" in text
    assert "version remains 0.93 until PR-14" in text


def test_decision_register_has_unique_complete_owner_decisions() -> None:
    text = _text(DECISIONS)
    ids = re.findall(r"^\| (D094-\d{3}) \|", text, flags=re.MULTILINE)
    assert ids == [f"D094-{i:03d}" for i in range(1, 22)]
    assert len(ids) == len(set(ids))
    assert "global code-compliance conclusion" in text


def test_supplied_review_fixture_is_hash_pinned_and_engineering_bounded() -> None:
    fixture = json.loads(_text(FIXTURE))
    assert fixture["programme_base"] == {
        "commit": BASE,
        "tree": TREE,
        "product_version": "0.93",
        "project_schema": 24,
    }
    reports = fixture["supplied_artifacts"]["reports"]
    assert [(row["profile"], row["pages"]) for row in reports] == [
        ("Standard", 69),
        ("Audit", 78),
        ("Brief", 4),
    ]
    for row in reports:
        assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
    for digest in fixture["supplied_artifacts"]["screenshots"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", digest)

    nm = fixture["nm_prestress"]
    assert nm["tendon"]["x_mm"] == 45.0
    assert nm["reinforcement_rows"] == [
        {
            "y_mm": -250.0,
            "x_start_mm": -150.0,
            "x_end_mm": 150.0,
            "count": 6,
            "diameter_mm": 20.0,
        },
        {
            "y_mm": 250.0,
            "x_start_mm": -150.0,
            "x_end_mm": 150.0,
            "count": 2,
            "diameter_mm": 20.0,
        },
    ]
    assert nm["materials"]["concrete"]["fck_mpa"] == 40.0
    assert nm["materials"]["mild_steel"]["fytk_mpa"] == 550.0
    assert nm["materials"]["prestressing_steel"][
        "initial_prestrain_per_mille"
    ] == 7.0
    assert nm["sweep"] == {
        "angles_deg": [90.0, 270.0, 0.0, 180.0],
        "points_per_branch": 32,
        "unreachable_squash_probe_kn": 10000000.0,
    }
    assert nm["acceptance"]["solver_tolerance_unchanged"] is True

    fatigue = fixture["fatigue_zero_range"]
    assert fatigue["cyclic_action_vector"] == [0.0, 0.0, 0.0]
    assert fatigue["acceptance"] == {
        "stress_range_mpa": 0.0,
        "miner_damage": 0.0,
        "life": "positive_infinity",
    }


def test_owner_amendments_freeze_report_ownership_and_lean_testing() -> None:
    programme = _text(PROGRAMME)
    decisions = _text(DECISIONS)
    assert "every report-related input, metadata field" in decisions
    assert "Report is a peer workspace to the right of Analysis" in programme
    assert "Inputs keeps only project-file operations" in programme
    assert "Development PRs run only" in programme
    assert "PR-14 first runs the complete" in programme


def test_final_version_gate_and_codex_review_order_are_unambiguous() -> None:
    programme = _text(PROGRAMME)
    decisions = _text(DECISIONS)
    assert "while the product still identifies as\n0.93" in programme
    assert "raise every governed version surface to\n0.94" in programme
    assert "packaging gates against the bumped build" in programme
    assert "GitHub Codex Review integration must\nreview the complete final head" in programme
    assert "Local or subagent review is supplementary" in programme
    assert "Every implementation PR requires a clean GitHub Codex Review" in decisions


def test_stale_report_profile_crash_is_frozen_for_pr09() -> None:
    fixture = json.loads(_text(FIXTURE))
    state = fixture["report_observations"]["stale_profile_state"]
    assert state == {
        "widget_key": "rep_report_content",
        "recognised_legacy_values_migrate": True,
        "unknown_value_resets_to": "Standard",
        "visible_notice": True,
        "old_report_invalidated": True,
        "app_execution_continues": True,
    }

    programme = _text(PROGRAMME)
    decisions = _text(DECISIONS)
    assert "durable profile recovery" in programme
    assert "never aborts app execution" in programme
    assert "A stale persisted report-profile selection must never abort" in decisions
