"""Exact tuple guard for the owner-directed calculation-trace retirement."""

from __future__ import annotations

from pathlib import Path
import re

from sector import __version__


ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "qa_v0.92_closure.md"
CONTRACT = ROOT / "docs" / "pr11d1_trace_retirement_reconciliation.md"

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


def test_retirement_is_complete_and_current_release_is_0_92() -> None:
    contract = " ".join(CONTRACT.read_text(encoding="ascii").split())
    assert "no calculation-trace data contract" in contract
    assert "trace switch" in contract
    assert "direct calculations and results" in contract
    assert __version__ == "0.92"
