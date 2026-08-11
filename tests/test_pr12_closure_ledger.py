"""Exact accepted-lineage and ledger guards for PR-12D."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

import pytest
ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "qa_v0.92_closure.md"
CLOSURE_MAP = ROOT / "docs" / "pr12d_pr12_closure_map.md"

SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")
PR_RE = re.compile(r"/pull/(\d+)\)")

EXPECTED_SLICES = (
    (
        "PR-12A1",
        "40a0e581631b9538c6af0f1f7241d9e6310690c0",
        "602608b50c1a27a0ed436513b2efa3a53d7c0d0d",
        "81e0310790246b2445a65c0d564e8a211d3024d2",
        334,
    ),
    (
        "PR-12A2",
        "3da762b31dfa449d3e1e72f68eaab433089574c9",
        "dca6f71c2e6d26292c6b9631674d493d9c0da71d",
        "1398b5ac7b1b0e8c2fc209dae764d5fa09df1c8c",
        335,
    ),
    (
        "PR-12B",
        "1f47e8ccd88465a95434d3d3384937af6e46567d",
        "0821ecd55dcf8c28420ff8a25a243aaf97494e3b",
        "051d6ad4b096b775d7d3ca9ef44af9ab635f0609",
        336,
    ),
    (
        "PR-12C1",
        "412463883e1a98a134773bbe3965335d660aa326",
        "b567d807b0d73789a7d848aeee76acb4009b194b",
        "3d997cea4058f5b0b916e75e88bbc18a235be29a",
        339,
    ),
    (
        "PR-12C2",
        "2e2a4bdcb296bf100339860de4518dd2eeb48b61",
        "fee56dce295af06cb7ac64a0ffe7885622c70d0c",
        "f4f725a21eda897dbaf98126e509bed21001bdc1",
        340,
    ),
)

EXPECTED_FINDINGS = {
    "F-018": [(EXPECTED_SLICES[0][1], 334)],
    "F-025": [(EXPECTED_SLICES[2][1], 336), (EXPECTED_SLICES[4][1], 340)],
    "F-026": [(EXPECTED_SLICES[0][1], 334), (EXPECTED_SLICES[1][1], 335)],
    "F-027": [(EXPECTED_SLICES[2][1], 336), (EXPECTED_SLICES[4][1], 340)],
    "F-028": [(EXPECTED_SLICES[3][1], 339), (EXPECTED_SLICES[4][1], 340)],
}

EXPECTED_CLOSURE_SLICES = {
    "F-018": ("PR-12A1",),
    "F-025": ("PR-12B", "PR-12C2"),
    "F-026": ("PR-12A1", "PR-12A2"),
    "F-027": ("PR-12B", "PR-12C2"),
    "F-028": ("PR-12C1", "PR-12C2"),
}

SUPERSEDED_HEADS = {
    "928f17200f0aef27ba5e00ad8c2fa014dfcec451",
    "55730a3ed65276b8e05da85e0a5c0e1d9ed8d1b1",
    "ac9e5ca989d967a05970fec602964f28764b5dcf",
}


def _finding_rows() -> dict[str, list[str]]:
    rows = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| F-"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 10:
            rows[cells[0]] = cells
    return rows


def _closure_finding_slices(text: str | None = None) -> dict[str, tuple[str, ...]]:
    rows = {}
    source = text if text is not None else CLOSURE_MAP.read_text(encoding="utf-8")
    for line in source.splitlines():
        if not line.startswith("| F-"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 3
        rows[cells[0]] = tuple(
            item.strip() for item in cells[1].split(",") if item.strip()
        )
    return rows


def test_closure_map_binds_five_exact_accepted_slice_tuples() -> None:
    actual = []
    for line in CLOSURE_MAP.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| PR-12"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 5
        head = SHA_RE.findall(cells[1])
        tree = SHA_RE.findall(cells[2])
        merge = SHA_RE.findall(cells[3])
        pr = [int(value) for value in PR_RE.findall(cells[4])]
        assert len(head) == len(tree) == len(merge) == len(pr) == 1
        actual.append((cells[0], head[0], tree[0], merge[0], pr[0]))

    assert tuple(actual) == EXPECTED_SLICES
    assert not SUPERSEDED_HEADS.intersection(row[1] for row in actual)


def test_pr12_ledger_heads_and_prs_are_positionally_bound() -> None:
    rows = _finding_rows()

    for finding, expected_pairs in EXPECTED_FINDINGS.items():
        row = rows[finding]
        assert row[1] == "PR-12"
        assert row[2] == "Merged and independently closed"
        heads = SHA_RE.findall(row[7])
        prs = [int(value) for value in PR_RE.findall(row[8])]
        assert list(zip(heads, prs, strict=True)) == expected_pairs
        assert "Pending" not in " | ".join(row)


def test_finding_map_uses_each_accepted_slice_without_scope_expansion() -> None:
    contract = " ".join(CLOSURE_MAP.read_text(encoding="ascii").split())
    closure_slices = _closure_finding_slices()
    evidence_by_slice = {
        slice_name: (head, pr)
        for slice_name, head, _tree, _merge, pr in EXPECTED_SLICES
    }
    accepted_by_finding: dict[str, set[str]] = defaultdict(set)
    actual_findings = {}
    for finding, slices in closure_slices.items():
        actual_findings[finding] = [evidence_by_slice[item] for item in slices]
    for finding, pairs in actual_findings.items():
        accepted_by_finding[finding].update(head for head, _pr in pairs)

    assert closure_slices == EXPECTED_CLOSURE_SLICES
    assert actual_findings == EXPECTED_FINDINGS
    assert set(accepted_by_finding) == {"F-018", "F-025", "F-026", "F-027", "F-028"}
    assert "makes no zero-long-task claim" in contract
    assert "PR-13 and PR-14 remain planned" in contract
    assert "changes no solver, formula, result, project schema" in contract


@pytest.mark.parametrize(
    "before, after",
    [
        ("| F-018 | PR-12A1 |", "| F-018 | PR-12A2 |"),
        ("| F-025 | PR-12B, PR-12C2 |", "| F-025 | PR-12C2, PR-12B |"),
        ("| F-026 | PR-12A1, PR-12A2 |", "| F-026 | PR-12A1, PR-12Z |"),
        ("| F-027 | PR-12B, PR-12C2 |", "| F-027 | PR-12B, PR-12B |"),
        ("| F-028 | PR-12C1, PR-12C2 |", "| F-029 | PR-12C1, PR-12C2 |"),
    ],
)
def test_finding_map_rejects_scope_mutations(before: str, after: str) -> None:
    source = CLOSURE_MAP.read_text(encoding="utf-8")
    mutated = source.replace(before, after, 1)
    assert mutated != source
    assert _closure_finding_slices(mutated) != EXPECTED_CLOSURE_SLICES
