"""Exact tuple guard for the owner-directed calculation-trace retirement."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "qa_v0.92_closure.md"
CONTRACT = ROOT / "docs" / "pr11d1_trace_retirement_reconciliation.md"
PR03_ACCEPTANCE = (
    ROOT / "docs" / "pr03_v093_textbook_calculation_publication_acceptance.md"
)
PROJECT_IO = ROOT / "app" / "project_io.py"

FORBIDDEN_CONTRACT_MODULES = {
    "app/calculation_evidence.py",
    "app/calculation_trace.py",
    "app/evidence_contract.py",
    "app/trace_contract.py",
    "app/trace_evaluator.py",
    "app/trace_workspace.py",
    "sector/calculation_evidence.py",
    "sector/calculation_trace.py",
    "sector/evidence_contract.py",
    "sector/trace_contract.py",
}

# Exact retired product identities only. Ordinary family-specific uses of the
# English words "trace" and "evidence" remain legitimate and are not banned.
FORBIDDEN_PRODUCT_IDENTIFIERS = {
    "calculation_evidence",
    "calculation_evidences",
    "calculation_trace",
    "calculation_traces",
    "calculation_trace_enabled",
    "calculation_trace_selection",
    "evidence_payload",
    "trace_appendix",
    "trace_history",
    "trace_mode",
    "trace_payload",
    "trace_seal",
    "trace_switch",
    "trace_view",
    "trace_workspace",
}

FORBIDDEN_PRODUCT_LABELS = {
    "Calculation Trace",
    "Calculation Trace Appendix",
    "Calculation Trace Workspace",
    "Trace Appendix",
    "Trace Mode",
}

FORBIDDEN_GENERIC_TYPES = {
    "CalculationEvidence",
    "CalculationEvidenceBundle",
    "CalculationEvidenceContract",
    "CalculationTrace",
    "CalculationTraceBundle",
    "CalculationTraceContract",
    "EvidenceDAG",
    "EvidenceGraph",
    "ParallelEvaluator",
    "TraceBuilder",
    "TraceDAG",
    "TraceEvaluator",
    "TraceGraph",
    "TraceRecorder",
}

EXPECTED_RETIREMENT = {
    (
        "R1 publication output",
        "e88763932cd8917a572c657aa1d8bef5503e2f50",
        "b162dd31ae0948c8238adae834682835f7355014",
        "311",
    ),
    (
        "R2 elastic and interaction families",
        "ad7f231b07378666233aeeb0575ad408bb78dd5d",
        "39e6ff832da2b485c494d2e7931a21ee7e1cff08",
        "312",
    ),
    (
        "R3 bridge, crack and fatigue families",
        "8f9504a50f59119c5c979dde8e7bf4479120f6d5",
        "f20b8e22656c621c5f8c10f96308587d8178dc76",
        "314",
    ),
    (
        "R4 shear, torsion and detailing families",
        "bf0acc136db7eb069029cdb5f980482f1a1b73b3",
        "d3e9769b227506cb34a3a78ffd859527ad45b417",
        "315",
    ),
    (
        "R5 core removal",
        "8c79f48365671960e8ad53d584605aca742cd1e5",
        "3e05c71ebb65ddc3ea8a00f8d7f2f81fcfce2c5b",
        "316",
    ),
}


def _markdown_rows(path: Path, prefix: str, width: int) -> list[tuple[str, ...]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith(prefix):
            continue
        cells = tuple(
            cell.strip().strip("`")
            for cell in line.strip("|").split("|")
        )
        assert len(cells) == width, (cells[0], len(cells))
        rows.append(cells)
    assert len(rows) == len(set(rows))
    return rows


def _production_sources() -> tuple[Path, ...]:
    sources = [ROOT / "run_app.py"]
    for folder in (ROOT / "app", ROOT / "sector"):
        sources.extend(folder.rglob("*.py"))
    return tuple(sorted(sources))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _identifiers(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg) or (
            isinstance(node, ast.keyword) and node.arg is not None
        ):
            names.add(node.arg)
        elif isinstance(
            node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            names.add(node.name)
    return names


def _strings(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) is str
    }


def _name_tokens(name: str) -> set[str]:
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()
    return set(re.findall(r"[a-z0-9]+", snake))


def _literal_assignment(path: Path, name: str) -> object:
    for statement in _tree(path).body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            assert statement.value is not None
            return ast.literal_eval(statement.value)
    raise AssertionError(f"{name} is not a literal assignment in {path}")


def test_retirement_table_binds_each_complete_accepted_tuple() -> None:
    actual = set(_markdown_rows(CONTRACT, "| R", 4))
    assert actual == EXPECTED_RETIREMENT


def test_trace_findings_are_retired_with_exact_closure_columns() -> None:
    rows = {
        cells[0]: cells
        for cells in _markdown_rows(LEDGER, "| F-", 10)
    }
    for finding in ("F-016", "F-030", "F-031"):
        row = rows[finding]
        assert row[1] == "Retired by R1-R5"
        assert row[2] == "Superseded by owner direction"
        assert row[7] == "8c79f48365671960e8ad53d584605aca742cd1e5"
        assert set(re.findall(r"/pull/(\d+)", row[8])) == {
            "311", "312", "314", "315", "316",
        }


def test_retirement_is_complete() -> None:
    contract = " ".join(CONTRACT.read_text(encoding="ascii").split())
    assert "no calculation-trace data contract" in contract
    assert "trace switch" in contract
    assert "direct calculations and results" in contract


def test_pr03_acceptance_is_bound_to_the_retirement_authority() -> None:
    acceptance = " ".join(
        PR03_ACCEPTANCE.read_text(encoding="ascii").split()
    )
    required = {
        "Repository revision: `b328144abf175e0025c796da929dfe01fd843293`",
        "Programme branch: `codex/pr03-v093-textbook-calculations`",
        (
            "Trace-retirement authority: [PR-11D1 reconciliation]"
            "(pr11d1_trace_retirement_reconciliation.md)"
        ),
        (
            "The complete calculation-trace subsystem from the previous "
            "programme's PR-08 was deliberately retired."
        ),
        "a cross-family calculation-trace or calculation-evidence data contract",
        "a generic calculation DAG, recorder, tolerant builder or parallel evaluator",
        "a trace switch, trace viewer, trace workspace, trace appendix or trace mode",
        "a top-level trace/evidence payload in calculation results",
        "persisted calculation history, a separate trace seal or a project-schema key",
        "The existing result objects are the only numerical authority.",
        "This PR does not change project schema 24",
        "The runtime version remains 0.92",
    }
    missing = sorted(fragment for fragment in required if fragment not in acceptance)
    assert not missing
    assert _literal_assignment(PROJECT_IO, "VERSION") == 24


def test_pr03_does_not_restore_retired_contract_payload_or_product_surfaces() -> None:
    sources = _production_sources()
    relative_sources = {
        path.relative_to(ROOT).as_posix() for path in sources
    }
    assert not FORBIDDEN_CONTRACT_MODULES & relative_sources

    identifier_violations: dict[str, list[str]] = {}
    label_violations: dict[str, list[str]] = {}
    generic_type_violations: dict[str, list[str]] = {}
    for path in sources:
        relative = path.relative_to(ROOT).as_posix()
        tree = _tree(path)
        identifiers = _identifiers(tree)
        strings = _strings(tree)
        retired_identifiers = sorted(
            FORBIDDEN_PRODUCT_IDENTIFIERS & (identifiers | strings)
        )
        if retired_identifiers:
            identifier_violations[relative] = retired_identifiers
        retired_labels = sorted(FORBIDDEN_PRODUCT_LABELS & strings)
        if retired_labels:
            label_violations[relative] = retired_labels

        generic_names: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            tokens = _name_tokens(node.name)
            explicitly_retired = node.name in FORBIDDEN_GENERIC_TYPES
            generic_trace_contract = (
                bool(tokens & {"trace", "evidence"})
                and bool(tokens & {"calculation", "cross", "generic", "shared"})
                and bool(
                    tokens
                    & {
                        "builder",
                        "bundle",
                        "contract",
                        "dag",
                        "evaluator",
                        "graph",
                        "recorder",
                    }
                )
            )
            if explicitly_retired or generic_trace_contract:
                generic_names.append(node.name)
        if generic_names:
            generic_type_violations[relative] = sorted(set(generic_names))

    assert not identifier_violations
    assert not label_violations
    assert not generic_type_violations


def test_pr03_has_no_parallel_calculation_evaluator() -> None:
    violations: dict[str, list[str]] = {}
    for path in _production_sources():
        tree = _tree(path)
        found: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            tokens = _name_tokens(node.name)
            if "parallel" in tokens and tokens & {
                "evaluate",
                "evaluation",
                "evaluator",
            }:
                found.add(node.name)
        if found:
            violations[path.relative_to(ROOT).as_posix()] = sorted(found)
    assert not violations
