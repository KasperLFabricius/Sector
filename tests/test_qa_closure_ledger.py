"""Consistency guard for the accepted v0.92 QA-roadmap ledger."""

from __future__ import annotations

from pathlib import Path

from sector import __version__


ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "qa_v0.92_closure.md"
ACCEPTANCE = ROOT / "docs" / "pr11d_qa_ledger_reconciliation_acceptance.md"


def _finding_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| F-"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == 10, (cells[0], len(cells))
        assert cells[0] not in rows
        rows[cells[0]] = cells
    return rows


def _retirement_rows() -> set[tuple[str, str, str, str]]:
    rows = set()
    for line in ACCEPTANCE.read_text(encoding="ascii").splitlines():
        if not line.startswith("| R"):
            continue
        cells = tuple(
            cell.strip().strip("`")
            for cell in line.strip("|").split("|")
        )
        assert len(cells) == 4, (cells[0], len(cells))
        assert cells not in rows
        rows.add(cells)
    return rows


TRACE_RETIREMENT = {
    "F-016": "8c79f48365671960e8ad53d584605aca742cd1e5",
    "F-030": "8c79f48365671960e8ad53d584605aca742cd1e5",
    "F-031": "8c79f48365671960e8ad53d584605aca742cd1e5",
}

RETIREMENT_IDENTITIES = {
    (
        "R1 publication surfaces",
        "e88763932cd8917a572c657aa1d8bef5503e2f50",
        "b162dd31ae0948c8238adae834682835f7355014",
        "#311",
    ),
    (
        "R2 elastic and interaction stacks",
        "ad7f231b07378666233aeeb0575ad408bb78dd5d",
        "39e6ff832da2b485c494d2e7931a21ee7e1cff08",
        "#312",
    ),
    (
        "R3 bridge, crack and fatigue stacks",
        "8f9504a50f59119c5c979dde8e7bf4479120f6d5",
        "f20b8e22656c621c5f8c10f96308587d8178dc76",
        "#314",
    ),
    (
        "R4 shear, torsion and detailing stacks",
        "bf0acc136db7eb069029cdb5f980482f1a1b73b3",
        "d3e9769b227506cb34a3a78ffd859527ad45b417",
        "#315",
    ),
    (
        "R5 core residue",
        "8c79f48365671960e8ad53d584605aca742cd1e5",
        "3e05c71ebb65ddc3ea8a00f8d7f2f81fcfce2c5b",
        "#316",
    ),
}

ACCEPTED_FINDING_HEADS = {
    "F-017": ("8de002c85e4bac0c24b6075319c519cfb44f71ba",),
    "F-019": (
        "bda00599af25f2d3b1869b1469987db85cc0e1de",
        "48faa10364473c2245b4a04632fafa7f32f052cf",
    ),
    "F-032": ("bc74309e193d362ae015fc68e78a802a9e43a87d",),
    "F-033": ("8de002c85e4bac0c24b6075319c519cfb44f71ba",),
    "F-034": ("9b5d11a4529581f6404941cca3355d27b637bc58",),
    "F-035": ("8de002c85e4bac0c24b6075319c519cfb44f71ba",),
    "F-036": ("204a83b89b1df62779179f6e84c52916673a46db",),
    "F-037": ("48faa10364473c2245b4a04632fafa7f32f052cf",),
    "F-038": ("257adb0171ef47327300041b580c5a6ed54245ad",),
    "F-039": (
        "bda23848498c21766134d276c1e5824d16cbc66a",
        "0852b6abb8f95bbb097b117bc4f658406b26ccfd",
        "75d5e2a07876185abda439344cb2c0472c70e058",
        "abc2eb7d6ba49116ec51f110383106d1e95e619b",
        "1b9c87536ba8b2709c1e737b3629f452ef5819d3",
        "7e88b5599159a699152345151ee9f4eedf3bb12c",
    ),
    "F-040": ("e602901161dfa463145fc10e848f3d197a587d76",),
    "F-041": (
        "d396238727172849b7ffa6d299fdb5916e05f200",
        "5cb7e63f3e22d4495c98168c7fe33d989c6b9bb4",
        "e812dc7c92c31c6bb6f62e287b07502e7f08ceb4",
        "ab1456e6e2b5f628353053bdc39ba1532a161441",
    ),
    "F-042": (
        "fa000b0feabdb6355e11b7a339a0b0a5f9ca3d12",
        "f95b6d92afea4de92bb8f76820761631566af938",
    ),
}


def test_trace_only_findings_are_superseded_by_accepted_retirement() -> None:
    rows = _finding_rows()
    acceptance = ACCEPTANCE.read_text(encoding="ascii")
    for finding, representative_head in TRACE_RETIREMENT.items():
        row = rows[finding]
        assert row[1] == "Superseded / retired"
        assert row[2] == "Superseded by owner-directed trace retirement"
        assert representative_head in " ".join(row)
    assert _retirement_rows() == RETIREMENT_IDENTITIES
    flat_acceptance = " ".join(acceptance.split())
    assert "no calculation-trace payload" in flat_acceptance
    assert "optional trace toggle" in flat_acceptance


def test_pr09_to_pr11_rows_bind_their_accepted_exact_heads() -> None:
    rows = _finding_rows()
    for finding, heads in ACCEPTED_FINDING_HEADS.items():
        row = rows[finding]
        assert row[2] == "Merged and independently closed"
        joined = " ".join(row)
        assert "Pending" not in joined
        assert "Planned" not in joined
        for head in heads:
            assert head in joined


def test_future_programme_rows_remain_planned_and_version_is_frozen() -> None:
    rows = _finding_rows()
    for finding in ("F-018", "F-025", "F-026", "F-027", "F-028"):
        assert rows[finding][1:3] == ["PR-12", "Planned"]
    for finding in ("F-012", "F-013"):
        assert rows[finding][1:3] == ["PR-13", "Planned"]
    for finding in ("F-014", "F-015", "F-021"):
        assert rows[finding][1:3] == ["PR-14", "Planned"]
    assert __version__ == "0.91"
