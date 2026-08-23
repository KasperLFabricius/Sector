import json
import re
from pathlib import Path

from sector import __version__

ROOT = Path(__file__).resolve().parents[1]
PROGRAMME = ROOT / "docs" / "v096_pr_programme.md"
DECISIONS = ROOT / "docs" / "v096_decision_register.md"
ACCEPTANCE = ROOT / "docs" / "pr01_v096_programme_acceptance.md"
PR06_ACCEPTANCE = ROOT / "docs" / "pr06_v096_gamma_v_acceptance.md"
PR07_ACCEPTANCE = ROOT / "docs" / "pr07_v096_reference_notation_acceptance.md"
FIXTURE = ROOT / "tests" / "fixtures" / "v096_review_cases.json"
PROJECT_IO = ROOT / "app" / "project_io.py"

BASE = "df397b2372e2e49b7a2165b0573ea0913e8c94dd"
TREE = "65eb685d0415cfe7852106838bbf51cc216449ab"
DEVELOPMENT_PRS = [f"PR-{number:02d}" for number in range(1, 10)]
NODES = [*DEVELOPMENT_PRS, "G1", "PR-10", "G2"]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fixture() -> dict:
    return json.loads(_text(FIXTURE))


def test_pr01_freezes_exact_current_main_without_bumping_product() -> None:
    base = _fixture()["programme_base"]
    assert base == {
        "commit": BASE,
        "tree": TREE,
        "product_version": "0.95",
        "project_schema": 26,
        "release_tag": "v0.95",
        "release_tag_commit": "7ab0062de37e08ebcd42330fcefcf62dd717002c",
        "current_main_qa_run": 32584442230,
    }
    assert __version__ == "0.95"
    acceptance = _text(ACCEPTANCE)
    assert "changes no runtime, solver, UI, report" in acceptance
    assert "Project schema retained by this PR: 26" in acceptance


def test_pr06_owns_bounded_schema_27_transition_without_bumping_product() -> None:
    project_io = _text(PROJECT_IO)
    assert __version__ == "0.95"
    assert re.search(r"^VERSION\s*=\s*27$", project_io, re.MULTILINE)
    assert re.search(r"^MIGRATABLE_VERSION\s*=\s*26$", project_io, re.MULTILINE)
    assert re.search(
        r"^LEGACY_MIGRATABLE_VERSION\s*=\s*25$",
        project_io,
        re.MULTILINE,
    )

    acceptance = _text(PR06_ACCEPTANCE)
    for phrase in (
        "Project schema before this PR: 26",
        "Product version retained by this PR: 0.95",
        "Schemas 25 and 26",
        "malformed and future schemas remain fail-closed",
    ):
        assert phrase in acceptance


def test_pr07_freezes_references_neutral_language_and_strain_notation() -> None:
    acceptance = " ".join(_text(PR07_ACCEPTANCE).split())
    for phrase in (
        "Base: `1cc32c438542f57cf7fb25d47848f8abeeaf46bb`",
        "Base tree: `3541bf5647fd1ba69b0b1e814c3bdf45f67cb674`",
        "Product version remains `0.95`; project schema remains `27`",
        "single source for the creep coefficient and the three detailing controls",
        "DS/EN 1992-1-1:2023, 5.2.4(1)-(3), Formula (5.11)",
        "DS/EN 1992-1-1:2023, 5.3.3(1)-(3), Formula (5.12)",
        "A zero crack-width limit is described as no limit comparison",
        "ASCII-safe Unicode identity `U+2030`",
        "stored defaults and material-law fractions are unchanged",
    ):
        assert phrase in acceptance


def test_pr_graph_is_exact_acyclic_and_owns_two_release_gates() -> None:
    graph = _fixture()["pr_graph"]
    assert graph["contract"] == "v096-pr-graph-v1"
    assert graph["development_prs"] == DEVELOPMENT_PRS
    assert graph["nodes"] == NODES
    dependencies = graph["dependencies"]
    assert list(dependencies) == NODES
    assert dependencies["PR-01"] == []
    for number in range(2, 10):
        assert dependencies[f"PR-{number:02d}"] == [f"PR-{number - 1:02d}"]
    assert dependencies["G1"] == DEVELOPMENT_PRS
    assert dependencies["PR-10"] == ["G1"]
    assert dependencies["G2"] == ["PR-10"]

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

    for node in NODES:
        visit(node)
    assert visited == set(NODES)


def test_programme_table_projects_all_prs_and_profile_philosophy() -> None:
    programme = _text(PROGRAMME)
    rows = re.findall(r"^\| (\d+) \| PR-(\d+) - ", programme, re.MULTILINE)
    assert rows == [(str(number), f"{number:02d}") for number in range(1, 11)]
    for phrase in (
        "Brief never reproduces substitutions, derivations, candidate searches or a",
        "complete effective calculation inputs used by every active result it",
        "Retaining inputs is distinct from reproducing the calculation chain",
        "Only the governing plastic and governing elastic",
        "Page count is not an acceptance target",
        "one governing worked calculation per active check family",
        "Audit retains complete candidates, branches, substitutions",
    ):
        assert phrase in programme

    profiles = _fixture()["profile_contract"]
    assert profiles["brief"][
        "complete_effective_inputs_for_reported_active_results"
    ] is True
    assert profiles["brief"]["inactive_or_unused_inputs_may_be_omitted"] is True
    assert profiles["brief"]["worked_result_chain"] is False
    assert profiles["brief"]["allowed_figure_families"] == [
        "governing plastic",
        "governing elastic",
    ]
    assert profiles["brief"]["page_count_target"] is None
    assert profiles["standard"]["complete_candidate_branches"] is False
    assert profiles["audit"]["complete_candidate_branches"] is True


def test_gamma_v_contract_is_exact_and_isolated_to_2023_shear() -> None:
    contract = _fixture()["gamma_v_contract"]
    assert contract == {
        "standard": "DS/EN 1992-1-1:2023",
        "definition_reference": "4.3.3 and Table 4.3 (NDP)",
        "calculation_reference": "8.2.2",
        "default": 1.4,
        "domain": "positive finite non-Boolean",
        "active_shear_model": "2023",
        "inactive_routes": ["2005 EN", "2005 DK NA", "torsion", "combined"],
        "backward_load_default": 1.4,
    }
    decisions = _text(DECISIONS)
    for phrase in (
        "Make `gamma_V` user-controlled for DS/EN 1992-1-1:2023 shear",
        "Clause 4.3.3 and",
        "Table 4.3 (NDP) give 1.40",
        "published but not implemented",
    ):
        assert phrase in decisions


def test_findings_are_contiguous_uniquely_owned_and_complete() -> None:
    findings = _fixture()["findings"]
    assert [row["id"] for row in findings] == [
        f"F096-{number:03d}" for number in range(1, 15)
    ]
    assert {row["owning_pr"] for row in findings} == {
        "PR-02",
        "PR-03",
        "PR-04",
        "PR-05",
        "PR-06",
        "PR-07",
        "PR-08",
        "PR-09",
    }
    assert all(row["topic"] for row in findings)


def test_decisions_are_contiguous_and_product_identity_is_bounded() -> None:
    decisions = _text(DECISIONS)
    ids = re.findall(r"^\| (D096-\d{3}) \|", decisions, re.MULTILINE)
    assert ids == [f"D096-{number:03d}" for number in range(1, 20)]
    assert len(ids) == len(set(ids))
    assert "no certification, sign-off, approval or" in decisions
    exclusions = _fixture()["scope_exclusions"]
    assert "global compliance verdict" in exclusions
    assert "arbitrary report page-count targets" in exclusions
    assert "former-version narrative in the end-user manual" in exclusions


def test_lifecycle_policy_reserves_full_qa_for_g1_and_g2() -> None:
    policy = _fixture()["lifecycle_policy"]
    assert policy == {
        "development_version": "0.95",
        "target_version": "0.96",
        "development_prs": DEVELOPMENT_PRS,
        "development_full_ci_allowed": False,
        "development_subject_contains": "[skip ci]",
        "pre_bump_full_ci_owner": "G1",
        "version_bump_owner": "PR-10",
        "post_bump_full_ci_owner": "G2",
        "release_version": "0.96",
        "exact_head_review_required": True,
        "zero_unresolved_findings_required": True,
    }
    programme = _text(PROGRAMME)
    assert "G1 is the\nsole complete pre-bump qualification" in programme
    assert "PR-10 then changes version-governed surfaces only" in programme
    assert "Tag `v0.96`, GitHub release and" in programme
