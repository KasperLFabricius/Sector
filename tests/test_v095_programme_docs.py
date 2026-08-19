import hashlib
import importlib
import json
import re
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sector import __version__

ROOT = Path(__file__).resolve().parents[1]
PROGRAMME = ROOT / "docs" / "v095_pr_programme.md"
DECISIONS = ROOT / "docs" / "v095_decision_register.md"
FIXTURE = ROOT / "tests" / "fixtures" / "v095_review_cases.json"
PROJECT_IO = ROOT / "app" / "project_io.py"
BASE = "9abd4c89f71d1379e32085ecc6773e14de882e33"
TREE = "f5e98754f0f970749919e354957bfa34dd4eb7fe"
AMENDMENT_BASE = "ed3a94098eed7e76521e5e9a3e27e86c66226f60"
AMENDMENT_TREE = "790083ac2694bc2bfa7578dd8062a047be66c0b5"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fixture() -> dict:
    return json.loads(_text(FIXTURE))


def test_programme_freezes_exact_release_base_and_fifteen_slices() -> None:
    text = _text(PROGRAMME)
    assert BASE in text
    assert TREE in text
    assert "Sector 0.94" in text
    assert "current project schema: 25" in text

    rows = re.findall(r"^\| (\d+) \| PR-(\d+) - ", text, flags=re.MULTILINE)
    assert rows == [(str(i), f"{i:02d}") for i in range(1, 16)]
    assert "PR-01 through PR-14 and PR-A00 through\nPR-A10 retain product version 0.94" in text
    assert re.search(r"gate G1 is the sole\s+complete pre-bump qualification", text)
    assert "Only PR-15 may change governed version" in text


def test_owner_scope_freezes_exact_amendment_base_sequence_and_ownership() -> None:
    text = _text(PROGRAMME)
    assert AMENDMENT_BASE in text
    assert AMENDMENT_TREE in text
    rows = re.findall(r"^\| A(\d{2}) \| PR-A(\d{2}) - ", text, flags=re.MULTILINE)
    assert rows == [(f"{i:02d}", f"{i:02d}") for i in range(11)]
    pr05_row = re.search(
        r"^\| 5 \| PR-05 - Combined M-V-T prerequisite closure \| (.+?) \| Planned \|$",
        text,
        flags=re.MULTILINE,
    )
    assert pr05_row is not None
    assert pr05_row.group(1) == "PR-02 through PR-04, PR-A03"
    assert "PR-A02 and PR-A03 precede final PR-05 activation" in text
    assert "PR-A06 follows PR-05 publication closure" in text

    amendment = _fixture()["owner_scope_amendment"]
    assert amendment == {
        "date": "2026-08-19",
        "base_commit": AMENDMENT_BASE,
        "base_tree": AMENDMENT_TREE,
        "product_version": "0.94",
        "project_schema_at_base": 25,
        "project_schema_after_pr_a04": 26,
        "authorized_prs": [f"PR-A{i:02d}" for i in range(11)],
        "selectable_design_basis_added": False,
        "geometry_family_added": False,
        "global_project_verdict_added": False,
        "certification_or_approval_claim_added": False,
    }

    scope = _fixture()["owner_authorized_scope"]
    assert [row["id"] for row in scope] == [f"OA095-{i:03d}" for i in range(1, 10)]
    assert [row["owning_prs"] for row in scope] == [
        ["PR-A01"],
        ["PR-A02", "PR-A03"],
        ["PR-A04"],
        ["PR-A05"],
        ["PR-A06"],
        ["PR-A07"],
        ["PR-A08"],
        ["PR-A09"],
        ["PR-A10"],
    ]
    for row in scope:
        assert row["outcome"]
        assert row["acceptance_matrix_owners"] == row["owning_prs"]
        assert row["owner_outcome_frozen_here"] is True
        assert row["implementation_contract_frozen_here"] is False


def test_live_identity_remains_v094_and_schema_25_during_pr01() -> None:
    assert __version__ == "0.94"
    assert re.search(r"^VERSION\s*=\s*25$", _text(PROJECT_IO), re.MULTILINE)
    assert _fixture()["programme_base"] == {
        "commit": BASE,
        "tree": TREE,
        "product_version": "0.94",
        "project_schema": 25,
        "tag": "v0.94",
    }


def test_decision_register_has_unique_contiguous_owner_decisions() -> None:
    ids = re.findall(
        r"^\| (D095-\d{3}) \|", _text(DECISIONS), flags=re.MULTILINE
    )
    assert ids == [f"D095-{i:03d}" for i in range(1, 25)]
    assert len(ids) == len(set(ids))


def test_lifecycle_policy_defers_full_ci_and_requires_both_reviews() -> None:
    policy = _fixture()["lifecycle_policy"]
    assert policy == {
        "development_version": "0.94",
        "target_version": "0.95",
        "development_prs": [f"PR-{i:02d}" for i in range(1, 15)],
        "owner_addition_prs": [f"PR-A{i:02d}" for i in range(11)],
        "development_full_ci_allowed": False,
        "development_commit_subject_contains": "[skip ci]",
        "development_merge_subject_contains": "[skip ci]",
        "g1_repair_commit_subject_contains": "[skip ci]",
        "g1_repair_merge_subject_contains": "[skip ci]",
        "pre_bump_full_ci_owner": "G1",
        "pre_bump_version": "0.94",
        "independent_adversarial_exact_head": True,
        "official_codex_exact_head": True,
        "retrigger_both_after_change": True,
        "zero_unresolved_threads": True,
        "post_bump_full_qualification": True,
        "version_bump_owner": "PR-15",
        "version_bump_candidate_subject_contains": "[skip ci]",
        "version_bump_merge_subject_contains": "Release Sector 0.95",
        "version_bump_merge_message_forbids_case_insensitive": [
            "[skip ci]",
            "[ci skip]",
            "[no ci]",
            "[skip actions]",
            "[actions skip]",
        ],
        "version_bump_merge_message_forbids_skip_checks_trailer": True,
        "post_bump_full_ci_owner": "G2",
        "post_bump_full_ci_trigger": "PR-15 exact main push",
        "post_bump_exact_main_actions_receipt_required": True,
        "release_version": "0.95",
    }

    programme = _text(PROGRAMME)
    assert "They do not run the complete repository" in programme
    assert "squash-merge subject\nalso retains `[skip ci]`" in programme
    assert "a fresh independent adversarial reviewer" in programme
    assert "official GitHub Codex Review integration" in programme
    assert "Any push invalidates both receipts" in programme
    assert "every review thread is resolved" in programme
    assert "PR-15's candidate commit also contains `[skip ci]`" in programme
    assert "complete reviewed merge\ncommit message" in programme
    assert "subject, body and trailers" in programme
    assert "exact-SHA Actions run\nreceipt is required" in programme


def test_crack_fatigue_and_overview_matrices_are_deferred_to_owning_prs() -> None:
    contracts = _fixture()["deferred_acceptance_contracts"]
    assert set(contracts) == {"PR-A04", "PR-A05", "PR-A06"}

    crack = contracts["PR-A04"]
    assert crack["state"] == "must be frozen in owning PR before code"
    assert crack["required_matrix_topics"] == [
        "separate schema-26 ordinary persistence keys",
        "duration-matched positive and zero-no-comparison behavior",
        "schema-25 ordinary positive and blank migration",
        "schema-25 heightened Formula 7.100 operand migration",
        "heightened enable-disable and formula isolation",
        "malformed input and backward-save policy",
    ]
    assert crack["schema_keys_frozen_here"] is False
    assert crack["migration_values_frozen_here"] is False
    assert crack["implementation_evidence"] is False

    fatigue = contracts["PR-A05"]
    assert fatigue["state"] == "must be frozen in owning PR before code"
    assert fatigue["required_matrix_topics"] == [
        "eligible detail class to threshold mapping",
        "below boundary outcome",
        "exact equality outcome",
        "above boundary outcome",
        "unsupported detail fallback",
        "independent fatigue checks retained",
    ]
    assert fatigue["threshold_values_frozen_here"] is False
    assert fatigue["implementation_evidence"] is False

    overview = contracts["PR-A06"]
    assert overview["state"] == "must be frozen in owning PR before code"
    assert overview["required_matrix_topics"] == [
        "complete emitted status vocabulary",
        "ordered status precedence",
        "numeric governing selection",
        "numeric tie break",
        "status tie break",
        "case and direction provenance selection",
    ]
    assert overview["status_order_frozen_here"] is False
    assert overview["tie_break_frozen_here"] is False
    assert overview["implementation_evidence"] is False

    programme = _text(PROGRAMME)
    assert "Formula 7.100 operand in a separate schema-26 field" in programme
    assert "PR-A00 intentionally owns none of those implementation matrices" in programme


def test_g1_pr15_g2_gate_order_is_unambiguous() -> None:
    programme = _text(PROGRAMME)
    pre = programme.index("G1 runs the complete static")
    correct = programme.index("correct any failure in a separate bounded PR")
    bump = programme.index("PR-15 raises every governed")
    post = programme.index("G2 runs the complete exact-head 0.95 qualification")
    publish = programme.index("package gate before tag and release publication")
    assert pre < correct < bump < post < publish


def test_adversarial_findings_are_unique_owned_and_complete() -> None:
    findings = _fixture()["findings"]
    ids = [row["id"] for row in findings]
    assert ids == [f"F095-{i:03d}" for i in range(1, 14)]
    assert len(ids) == len(set(ids))
    assert {row["severity"] for row in findings} == {"P1", "P2"}
    assert [(row["id"], row["owning_pr"]) for row in findings] == [
        (f"F095-{i:03d}", f"PR-{i + 1:02d}") for i in range(1, 14)
    ]
    for row in findings:
        assert row["source_locations"]
        assert row["reproduction"]
        assert row["accepted_behavior"]
        assert row["excluded_behavior"]


def test_engineering_false_pass_cases_are_frozen_fail_closed() -> None:
    findings = {row["id"]: row for row in _fixture()["findings"]}
    origin = findings["F095-001"]
    assert origin["reproduction"]["observed_verdict"] == "PASS"
    assert origin["accepted_behavior"]["origin_outside_result"] == "invalid"
    assert origin["accepted_behavior"]["finite_pass_for_zero_or_small_demand"] is False

    cracking = findings["F095-002"]
    assert cracking["reproduction"]["prestress_only_concrete_tension_mpa"] > cracking[
        "reproduction"
    ]["fctm_mpa"]
    assert cracking["accepted_behavior"]["lambda_cr"] == 0.0
    assert cracking["accepted_behavior"]["cracked"] is True

    combined = findings["F095-004"]
    assert combined["reproduction"]["observed"]["verdict"] == "PASS"
    assert combined["reproduction"]["out"]["shear"]["res"]["valid"] is True
    invalid_links = combined["reproduction"]["controls"]["invalid_active_links"]
    assert invalid_links["shear"]["links"]["res"]["valid"] is False
    assert invalid_links["observed_combined_valid"] is True
    assert combined["accepted_behavior"]["combined_valid"] is False


def test_transaction_browser_and_qa_acceptance_is_fail_closed() -> None:
    findings = {row["id"]: row for row in _fixture()["findings"]}
    assert findings["F095-008"]["accepted_behavior"][
        "timeout_terminates_owned_process_tree"
    ] is True
    assert findings["F095-009"]["accepted_behavior"][
        "failed_decode_advances_identity"
    ] is False
    uploads = findings["F095-009"]["reproduction"]
    assert uploads["first_upload"]["size"] == uploads["changed_upload"]["size"] == 2147
    assert uploads["first_upload"]["sha256"] != uploads["changed_upload"]["sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", uploads["first_upload"]["sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", uploads["changed_upload"]["sha256"])
    assert uploads["invalid_then_fixed_pair"]["size"] == 2147
    assert uploads["invalid_then_fixed_pair"]["invalid_decode"] == "failure"
    assert findings["F095-010"]["accepted_behavior"][
        "saved_hash_updates_after_replace_only"
    ] is True
    assert findings["F095-011"]["accepted_behavior"][
        "script_or_event_execution"
    ] is False
    assert findings["F095-012"]["accepted_behavior"][
        "manual_guard_mandatory_in_locked_qa"
    ] is True


def test_upload_vectors_regenerate_with_the_documented_frozen_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "app"))
    project_io = importlib.import_module("project_io")

    reproduction = {
        row["id"]: row for row in _fixture()["findings"]
    }["F095-009"]["reproduction"]
    recipe = reproduction["valid_project_byte_recipe"]
    frozen_now = datetime.fromisoformat(recipe["frozen_datetime_now"])

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen_now.replace(tzinfo=None)
            return frozen_now.astimezone(tz)

    payloads = {}
    for key in ("first_upload", "changed_upload"):
        vector = reproduction[key]
        with patch.object(project_io, "datetime", FrozenDateTime):
            text = project_io.dump_project(
                {},
                {},
                app_version="0.94",
                revision=vector["revision"],
            )
        payload = text.encode("utf-8")
        payloads[key] = payload
        parsed = project_io.parse_project(text)
        assert len(payload) == vector["size"]
        assert hashlib.sha256(payload).hexdigest() == vector["sha256"]
        assert json.loads(text)["provenance"]["saved_at_utc"] == recipe[
            "saved_at_utc"
        ]
        assert parsed is not None

    invalid_vector = reproduction["invalid_then_fixed_pair"]
    invalid = b"\xff" + payloads["first_upload"][1:]
    assert len(invalid) == invalid_vector["size"]
    assert hashlib.sha256(invalid).hexdigest() == invalid_vector["invalid_sha256"]
    with pytest.raises(UnicodeDecodeError):
        invalid.decode("utf-8")
    fixed = payloads["first_upload"]
    assert hashlib.sha256(fixed).hexdigest() == invalid_vector["fixed_sha256"]
    assert invalid_vector["fixed_decode_and_parse"] == "success"
    assert project_io.parse_project(fixed.decode("utf-8")) is not None


def test_programme_bounds_owner_additions_and_preserves_non_findings() -> None:
    programme = _text(PROGRAMME)
    decisions = _text(DECISIONS)
    assert "adds no selectable design basis" in programme
    assert "no unapproved feature enters" in programme
    assert "Only D095-023 additions are authorized" in decisions
    assert "global compliance" in decisions
    deferred = _fixture()["deferred_observations"]
    assert [row["topic"] for row in deferred] == [
        "production export selector inventory",
        "manual hot-reload artifact identity",
        "cache, collapsed-work and dead-code maintenance",
    ]
    non_findings = _fixture()["non_findings"]
    assert [row["id"] for row in non_findings] == [
        f"N095-{i:03d}" for i in range(1, 9)
    ]
    assert non_findings[0] == {
        "id": "N095-001",
        "topic": "concrete equivalent-amplitude fatigue cycles",
        "decision": (
            "intentional disclosed one-million-cycle pair contract; "
            "no correctness change"
        ),
    }


def test_material_fixture_owns_complete_curve_specific_constructor_inputs() -> None:
    findings = {row["id"]: row for row in _fixture()["findings"]}
    reproduction = findings["F095-005"]["reproduction"]
    assert set(reproduction["mild_curve_3_base"]) == {
        "fytk",
        "fyck",
        "eut",
        "futk",
        "gamma_y",
        "gamma_u",
        "gamma_E",
        "curve",
        "k",
        "ey0t",
        "ey0c",
        "Es",
        "active_in_compression",
    }
    assert set(reproduction["prestress_curve_7_base"]) == {
        "curve",
        "IS",
        "gamma_y",
        "gamma_u",
        "gamma_E",
        "fytk",
        "eut",
        "futk",
        "k",
        "ey0t",
        "Es",
    }
    assert reproduction["relationship_cases"]
    assert reproduction["curve_applicability_controls"]
