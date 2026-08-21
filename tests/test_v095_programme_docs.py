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
FATIGUE_SCREEN_ACCEPTANCE = (
    ROOT / "docs" /
    "pr_a05_v095_simplified_reinforcement_fatigue_screen_acceptance.md"
)
PROJECT_IO = ROOT / "app" / "project_io.py"
BASE = "9abd4c89f71d1379e32085ecc6773e14de882e33"
TREE = "f5e98754f0f970749919e354957bfa34dd4eb7fe"
AMENDMENT_BASE = "ed3a94098eed7e76521e5e9a3e27e86c66226f60"
AMENDMENT_TREE = "790083ac2694bc2bfa7578dd8062a047be66c0b5"
GRAPH_MERGE = "9282a7ff56512b123fbb53a55ebf32565c093fe5"
GRAPH_TREE = "7e6980bb3d107f19336efbb0c2c4ef40f1b6cde1"
NARRATIVE_MERGE = "9fcb328e290f952c12b90778e5f0efe599a9381a"
NARRATIVE_TREE = "19fdb72b1d2300a67c94167df27e2b10b3662574"
HISTORICAL_DEVELOPMENT_PRS = [f"PR-{i:02d}" for i in range(1, 15)]
OWNER_IMPLEMENTATION_PRS = [f"PR-A{i:02d}" for i in range(1, 11)]
OWNER_DEVELOPMENT_PRS = [
    "PR-A00a1",
    "PR-A00a2",
    "PR-A00b",
    *OWNER_IMPLEMENTATION_PRS,
]
EXPECTED_OWNER_SEQUENCE_DEPENDENCIES = {
    "PR-01": [],
    "PR-02": ["PR-01"],
    "PR-03": ["PR-01"],
    "PR-04": ["PR-01"],
    "PR-05": ["PR-02", "PR-03", "PR-04", "PR-A03"],
    "PR-06": ["PR-05"],
    "PR-07": ["PR-06"],
    "PR-08": ["PR-02", "PR-07"],
    "PR-09": ["PR-03", "PR-07"],
    "PR-10": ["PR-06", "PR-07"],
    "PR-11": ["PR-07"],
    "PR-12": ["PR-01"],
    "PR-13": ["PR-09"],
    "PR-14": ["PR-09", "PR-13"],
    "PR-A00a1": [],
    "PR-A00a2": ["PR-A00a1"],
    "PR-A00b": ["PR-A00a2"],
    "PR-A01": ["PR-A00b"],
    "PR-A02": ["PR-A00b"],
    "PR-A03": ["PR-A02"],
    "PR-A04": ["PR-A00b"],
    "PR-A05": ["PR-A00b"],
    "PR-A06": ["PR-05", "PR-A04", "PR-A05"],
    "PR-A07": ["PR-A00b"],
    "PR-A08": ["PR-A00b"],
    "PR-A09": ["PR-A00b"],
    "PR-A10": ["PR-A00b"],
    "G1": [*HISTORICAL_DEVELOPMENT_PRS, *OWNER_DEVELOPMENT_PRS],
    "PR-15": ["G1"],
    "G2": ["PR-15"],
}


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
    assert re.search(
        r"PR-01 through PR-14, PR-A00a1, PR-A00a2, PR-A00b and PR-A01 through PR-A10\s+"
        r"retain product version 0\.94",
        text,
    )
    assert "It is the sole complete pre-bump qualification" in text
    assert "Only PR-15 may change governed version surfaces" in " ".join(text.split())


def test_owner_sequence_graph_is_exact_resolvable_and_acyclic() -> None:
    graph = _fixture()["owner_sequence_graph"]
    development_prs = [*HISTORICAL_DEVELOPMENT_PRS, *OWNER_DEVELOPMENT_PRS]
    nodes = [*development_prs, "G1", "PR-15", "G2"]

    assert graph["contract"] == "owner-sequence-graph-v1"
    assert graph["base_commit"] == AMENDMENT_BASE
    assert graph["base_tree"] == AMENDMENT_TREE
    assert graph["product_version"] == "0.94"
    assert graph["project_schema"] == 25
    assert graph["sequencing_only"] is True
    assert graph["narrative_contract_owner"] == "PR-A00a2"
    assert graph["scope_contract_owner"] == "PR-A00b"
    assert graph["implementation_contracts_frozen_here"] is False
    assert graph["development_prs"] == development_prs
    assert graph["nodes"] == nodes
    assert len(nodes) == len(set(nodes))

    dependencies = graph["dependencies"]
    assert dependencies == EXPECTED_OWNER_SEQUENCE_DEPENDENCIES
    assert list(dependencies) == nodes
    known = set(nodes)
    assert all(dependency in known for row in dependencies.values() for dependency in row)
    assert all(node not in row for node, row in dependencies.items())

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        assert node not in visiting
        if node in visited:
            return
        visiting.add(node)
        for dependency in dependencies[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in nodes:
        visit(node)
    assert visited == known


def test_owner_sequence_graph_freezes_cross_sequence_and_release_gates() -> None:
    graph = _fixture()["owner_sequence_graph"]
    dependencies = graph["dependencies"]

    assert dependencies["PR-A00a1"] == []
    assert dependencies["PR-A00a2"] == ["PR-A00a1"]
    assert dependencies["PR-A00b"] == ["PR-A00a2"]
    assert dependencies["PR-A03"] == ["PR-A02"]
    assert dependencies["PR-05"] == ["PR-02", "PR-03", "PR-04", "PR-A03"]
    assert dependencies["PR-A06"] == ["PR-05", "PR-A04", "PR-A05"]
    assert dependencies["G1"] == graph["development_prs"]
    assert dependencies["PR-15"] == ["G1"]
    assert dependencies["G2"] == ["PR-15"]

    assert all(
        dependency.startswith("PR-") or dependency in {"G1", "G2"}
        for row in dependencies.values()
        for dependency in row
    )


def test_owner_sequence_narrative_and_lifecycle_match_reviewed_graph() -> None:
    fixture = _fixture()
    graph = fixture["owner_sequence_graph"]
    dependencies = graph["dependencies"]
    programme = _text(PROGRAMME)
    compact_programme = " ".join(programme.split())

    assert AMENDMENT_BASE in programme
    assert AMENDMENT_TREE in programme
    assert GRAPH_MERGE in programme
    assert GRAPH_TREE in programme
    assert graph["narrative_contract_owner"] == "PR-A00a2"
    assert graph["scope_contract_owner"] == "PR-A00b"
    assert graph["implementation_contracts_frozen_here"] is False

    historical_rows = re.findall(
        r"^\| (\d+) \| (PR-\d{2}) - [^|]+ \| ([^|]+) \|",
        programme,
        flags=re.MULTILINE,
    )
    historical = {pr: dependency.strip() for _, pr, dependency in historical_rows}
    assert historical["PR-01"] == "released v0.94 baseline"
    for pr in HISTORICAL_DEVELOPMENT_PRS[1:]:
        assert historical[pr] == ", ".join(dependencies[pr])
    assert historical["PR-15"] == "G1"

    owner_rows = re.findall(
        r"^\| (A(?:00a1|00a2|00b|\d{2})) \| "
        r"(PR-A(?:00a1|00a2|00b|\d{2})) - [^|]+ \| ([^|]+) \| ([^|]+) \|$",
        programme,
        flags=re.MULTILINE,
    )
    assert [row[1] for row in owner_rows] == OWNER_DEVELOPMENT_PRS
    assert owner_rows[0][2:] == ("exact amendment base", "Merged")
    assert owner_rows[1][2:] == ("PR-A00a1", "Merged")
    assert owner_rows[2][2:] == ("PR-A00a2", "In progress")
    for _, pr, dependency, status in owner_rows[3:]:
        assert dependency == ", ".join(dependencies[pr])
        assert status == "Planned"

    g1_prs = ", ".join(dependencies["G1"][:-1])
    g1_prs = f"{g1_prs} and {dependencies['G1'][-1]}"
    assert f"implicit or omitted prerequisite: {g1_prs}." in compact_programme
    assert "PR-15 depends only on G1, and G2 depends only on PR-15" in compact_programme
    assert fixture["lifecycle_policy"]["development_prs"] == graph["development_prs"]
    assert "owner_authorized_scope" in fixture
    assert "deferred_acceptance_contracts" in fixture
    assert "PR-A00b now freezes the bounded outcomes" in compact_programme


def test_owner_scope_freezes_exact_amendment_identity_and_ownership() -> None:
    fixture = _fixture()
    graph = fixture["owner_sequence_graph"]
    amendment = fixture["owner_scope_amendment"]
    assert amendment == {
        "contract": "owner-scope-contract-v1",
        "owner_request_date": "2026-08-19",
        "contract_freeze_date": "2026-08-20",
        "amendment_base_commit": AMENDMENT_BASE,
        "amendment_base_tree": AMENDMENT_TREE,
        "graph_merge_commit": GRAPH_MERGE,
        "graph_merge_tree": GRAPH_TREE,
        "narrative_merge_commit": NARRATIVE_MERGE,
        "narrative_merge_tree": NARRATIVE_TREE,
        "product_version": "0.94",
        "project_schema_at_base": 25,
        "project_schema_after_pr_a04": 26,
        "scope_contract_owner": "PR-A00b",
        "implementation_prs": OWNER_IMPLEMENTATION_PRS,
        "selectable_design_basis_added": False,
        "geometry_family_added": False,
        "global_project_verdict_added": False,
        "certification_or_approval_claim_added": False,
    }
    assert amendment["scope_contract_owner"] == graph["scope_contract_owner"]
    assert all(pr in graph["nodes"] for pr in amendment["implementation_prs"])

    expected = [
        (
            "OA095-001",
            (
                "Compact the Standard-report ultimate-curvature substitution while "
                "retaining the complete candidate evidence."
            ),
            ["PR-A01"],
        ),
        (
            "OA095-002",
            (
                "Require current closed torsion links for full torsion resistance and "
                "make shear-link versus torsion-link semantics explicit across input, "
                "Results and publication."
            ),
            ["PR-A02", "PR-A03"],
        ),
        (
            "OA095-003",
            (
                "Use separate user-owned long-term and short-term ordinary crack-width "
                "criteria, with persistence, migration and heightened-formula "
                "isolation frozen in PR-A04."
            ),
            ["PR-A04"],
        ),
        (
            "OA095-004",
            (
                "Add a supported simplified reinforcement-fatigue screen before "
                "detailed reinforcement fatigue assessment."
            ),
            ["PR-A05"],
        ),
        (
            "OA095-005",
            (
                "Publish one always-visible governing Results Overview row per stable "
                "check family without a global project verdict."
            ),
            ["PR-A06"],
        ),
        (
            "OA095-006",
            (
                "Make analysis plot hovers disclose retained capacity, material, "
                "stress and strain evidence while coordinates remain in section "
                "input and preview plots."
            ),
            ["PR-A07"],
        ),
        (
            "OA095-007",
            (
                "Add selected-edition Eurocode provenance to creep and detailing "
                "inputs without extending supported applicability."
            ),
            ["PR-A08"],
        ),
        (
            "OA095-008",
            (
                "Publish retained plastic compression-zone depth c in the summary "
                "without relabelling it as generic effective reinforcement depth d."
            ),
            ["PR-A09"],
        ),
        (
            "OA095-009",
            (
                "Remove the complete reproducible reference from the end-user manual "
                "while retaining its generator, independent oracle, fixture and tests "
                "as QA assets."
            ),
            ["PR-A10"],
        ),
    ]
    scope = fixture["owner_authorized_scope"]
    assert [
        (row["id"], row["outcome"], row["owning_prs"]) for row in scope
    ] == expected
    assert [pr for row in scope for pr in row["owning_prs"]] == OWNER_IMPLEMENTATION_PRS
    for row in scope:
        assert row["acceptance_matrix_owners"] == row["owning_prs"]
        assert row["owner_outcome_frozen_here"] is True
        assert row["implementation_contract_frozen_here"] is (
            row["id"] == "OA095-004"
        )

    outcome_by_id = {row["id"]: row["outcome"] for row in scope}
    required_narrative_terms = {
        "OA095-002": ("input", "Results", "publication"),
        "OA095-006": ("section input", "preview plots"),
        "OA095-008": ("in the summary",),
        "OA095-009": ("independent oracle",),
    }
    for scope_id, terms in required_narrative_terms.items():
        assert all(term in outcome_by_id[scope_id] for term in terms)

    programme = _text(PROGRAMME)
    compact_programme = " ".join(programme.split())
    assert "The authorized outcomes are limited to" in compact_programme
    for phrase in [
        "ultimate-curvature substitution",
        "full torsion resistance from being assessed without current closed",
        "independent long-term and short-term user criteria",
        "simplified reinforcement-fatigue screen",
        "one always-visible governing row per stable check family",
        "analysis plot hovers publish retained capacity, material, stress and strain",
        "selected-edition Eurocode provenance to creep and detailing inputs",
        "plastic compression-zone depth `c`",
        "complete reproducible reference from the end-user manual",
    ]:
        assert phrase in compact_programme


def test_crack_fatigue_and_overview_matrices_are_deferred_to_owning_prs() -> None:
    contracts = _fixture()["deferred_acceptance_contracts"]
    assert set(contracts) == {"PR-A04", "PR-A05", "PR-A06"}

    crack = contracts["PR-A04"]
    assert crack == {
        "state": "must be frozen in owning PR before code",
        "required_matrix_topics": [
            "separate schema-26 ordinary persistence keys",
            "duration-matched positive and zero-no-comparison behavior",
            "schema-25 ordinary positive and blank migration",
            "schema-25 heightened Formula 7.100 operand migration",
            "heightened enable-disable and formula isolation",
            "malformed input and backward-save policy",
        ],
        "schema_keys_frozen_here": False,
        "migration_values_frozen_here": False,
        "implementation_evidence": False,
    }

    fatigue = contracts["PR-A05"]
    assert fatigue == {
        "state": (
            "frozen; calculation and UI implemented in PR-A05a, "
            "publication pending PR-A05b"
        ),
        "acceptance_document": (
            "docs/pr_a05_v095_simplified_reinforcement_fatigue_screen_"
            "acceptance.md"
        ),
        "required_matrix_topics": [
            "eligible detail class to threshold mapping",
            "below boundary outcome",
            "exact equality outcome",
            "above boundary outcome",
            "unsupported detail fallback",
            "independent fatigue checks retained",
        ],
        "threshold_values_frozen_here": True,
        "implementation_evidence": False,
    }

    overview = contracts["PR-A06"]
    assert overview == {
        "state": "must be frozen in owning PR before code",
        "required_matrix_topics": [
            "complete emitted status vocabulary",
            "ordered status precedence",
            "numeric governing selection",
            "numeric tie break",
            "status tie break",
            "case and direction provenance selection",
        ],
        "status_order_frozen_here": False,
        "tie_break_frozen_here": False,
        "implementation_evidence": False,
    }


def test_pr_a05_acceptance_freezes_mapping_boundaries_and_fallback() -> None:
    text = _text(FATIGUE_SCREEN_ACCEPTANCE)
    compact = " ".join(text.split())

    for required in (
        "70 MPa characteristic range",
        "35 MPa characteristic range",
        "90 MPa design range",
        "73 MPa design range",
        "40 MPa design range",
        "30 MPa design range",
        "19 MPa design range",
        "95 MPa design range",
        "80 MPa design range",
        "55 MPa design range",
        "range <= limit",
        "Exact equality therefore passes",
        "DETAILED CHECK REQUIRED",
        "NOT APPLICABLE",
        "yield/proof checks always remain independent",
        "detailed S-N/Miner evidence",
    ):
        assert required in compact

    programme = " ".join(_text(PROGRAMME).split())
    assert "Formula 7.100 operand in a separate schema-26 field" in programme
    assert "PR-A00b intentionally owns none of those implementation matrices" in programme


def test_live_identity_remains_v094_and_uses_a04_schema_26() -> None:
    assert __version__ == "0.94"
    assert re.search(r"^VERSION\s*=\s*26$", _text(PROJECT_IO), re.MULTILINE)
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
    assert ids == [f"D095-{i:03d}" for i in range(1, 26)]
    assert len(ids) == len(set(ids))
    decisions = _text(DECISIONS)
    assert "PR-A00a1 owns the complete machine-resolvable dependency graph" in decisions
    assert "PR-A00a2 projects that unchanged graph" in decisions
    assert "PR-A00b separately freezes owner outcomes" in decisions
    assert "Only the D095-024 outcomes are authorized" in decisions
    assert "PR-A00b freezes scope and ownership only" in decisions


def test_lifecycle_policy_defers_full_ci_and_requires_both_reviews() -> None:
    policy = _fixture()["lifecycle_policy"]
    assert policy == {
        "development_version": "0.94",
        "target_version": "0.95",
        "development_prs": _fixture()["owner_sequence_graph"]["development_prs"],
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
    assert uploads["first_upload"]["size"] == uploads["changed_upload"]["size"] == 2313
    assert uploads["first_upload"]["sha256"] != uploads["changed_upload"]["sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", uploads["first_upload"]["sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", uploads["changed_upload"]["sha256"])
    assert uploads["invalid_then_fixed_pair"]["size"] == 2313
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
    assert "Only the D095-024 outcomes are authorized" in decisions
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
