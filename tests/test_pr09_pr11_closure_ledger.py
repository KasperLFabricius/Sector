"""Independent closure-identity checks for PR-11D2."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

import sector


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "qa_v0.92_closure.md"
CLOSURE_MAP = ROOT / "docs" / "pr11d2_pr09_pr11_closure_map.md"

SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")
PR_RE = re.compile(r"/pull/(\d+)\)")

EXPECTED_ROWS = (
    ("F-017", "PR-09A", "8de002c85e4bac0c24b6075319c519cfb44f71ba", "7512c3ed01e41100cee59893ce9beab381bec890", 283),
    ("F-033", "PR-09A", "8de002c85e4bac0c24b6075319c519cfb44f71ba", "7512c3ed01e41100cee59893ce9beab381bec890", 283),
    ("F-035", "PR-09A", "8de002c85e4bac0c24b6075319c519cfb44f71ba", "7512c3ed01e41100cee59893ce9beab381bec890", 283),
    ("F-036", "PR-09B", "204a83b89b1df62779179f6e84c52916673a46db", "563d107d223541703f848e44c07ddfbcc22bd2d7", 287),
    ("F-034", "PR-10A1", "9b5d11a4529581f6404941cca3355d27b637bc58", "c19eaa4efdb6ee91a597bdc241ec08a24074dc9c", 290),
    ("F-040", "PR-10A2", "e602901161dfa463145fc10e848f3d197a587d76", "af2a835c3da31adc41ac3075dee0fb794ffa305b", 291),
    ("F-032", "PR-10B1a2", "bc74309e193d362ae015fc68e78a802a9e43a87d", "efd5516212777269be13a48c207ad1ad3c3b3050", 295),
    ("F-019", "PR-10B1b", "bda00599af25f2d3b1869b1469987db85cc0e1de", "def49c5f88da485950e82d74427d5c71e2326b2c", 296),
    ("F-019", "PR-10B2", "48faa10364473c2245b4a04632fafa7f32f052cf", "2c75c81b47e55e41a27dcf9d0351773672023ed0", 297),
    ("F-037", "PR-10B2", "48faa10364473c2245b4a04632fafa7f32f052cf", "2c75c81b47e55e41a27dcf9d0351773672023ed0", 297),
    ("F-038", "PR-11A1R2", "257adb0171ef47327300041b580c5a6ed54245ad", "96e1c5dfe9e6d48e9ff848ad025ed2806202b383", 299),
    ("F-039", "PR-11A2a", "bda23848498c21766134d276c1e5824d16cbc66a", "6d3336867ddaa449f9887551c96b76125dedb6c5", 301),
    ("F-039", "PR-11A2b", "0852b6abb8f95bbb097b117bc4f658406b26ccfd", "e25e730c5129a1b5f5a9a194e6bb91e2e5f761cf", 302),
    ("F-039", "PR-11A3a1L", "75d5e2a07876185abda439344cb2c0472c70e058", "469b7463da1d2b0fce819099751c86cdc35356ec", 308),
    ("F-039", "PR-11A3a1S", "abc2eb7d6ba49116ec51f110383106d1e95e619b", "8f687b0af00bc79748860cc5df9ccf9e451f793e", 309),
    ("F-039", "PR-11A3a2", "1b9c87536ba8b2709c1e737b3629f452ef5819d3", "141b1a9cb0ebed18d7ed84124d54327bae48909c", 317),
    ("F-039", "PR-11A3b", "7e88b5599159a699152345151ee9f4eedf3bb12c", "061d15cda6bb137068bcae2d31a97729500443df", 318),
    ("F-041", "PR-11B1", "d396238727172849b7ffa6d299fdb5916e05f200", "ed20ae984165750fc1a560d591ac9b1e1a3d1fe9", 320),
    ("F-041", "PR-11B2A", "5cb7e63f3e22d4495c98168c7fe33d989c6b9bb4", "738a31a32868adaedf32ecccbffde43d19de6d09", 322),
    ("F-041", "PR-11C1A", "e812dc7c92c31c6bb6f62e287b07502e7f08ceb4", "fbc2acffa5a9fa65be3d78a5def6219004c03038", 325),
    ("F-041", "PR-11C1B", "ab1456e6e2b5f628353053bdc39ba1532a161441", "e5c90ccc8c8ce730d534deba9331f8af6fcd36df", 326),
    ("F-042", "PR-11C2A", "fa000b0feabdb6355e11b7a339a0b0a5f9ca3d12", "53b0d7895a45ab570d04a5651d2502e873b0688a", 328),
    ("F-042", "PR-11C2B", "f95b6d92afea4de92bb8f76820761631566af938", "f0aa5b8de644a2a24d01a58a6e26c7af4b0690c7", 329),
)


def _finding_rows(path: Path) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| F-"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 10:
            rows[cells[0]] = cells
    return rows


def _expected_by_finding() -> dict[str, list[tuple[str, int]]]:
    expected: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for finding, _slice, candidate, _merge, pr_number in EXPECTED_ROWS:
        expected[finding].append((candidate, pr_number))
    return dict(expected)


def test_closure_map_binds_every_accepted_identity_as_one_exact_row() -> None:
    actual = []
    for line in CLOSURE_MAP.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| F-"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 5
        candidates = SHA_RE.findall(cells[2])
        merges = SHA_RE.findall(cells[3])
        prs = [int(value) for value in PR_RE.findall(cells[4])]
        assert len(candidates) == len(merges) == len(prs) == 1
        actual.append((cells[0], cells[1], candidates[0], merges[0], prs[0]))

    assert tuple(actual) == EXPECTED_ROWS
    assert len({(candidate, merge, pr) for _, _, candidate, merge, pr in actual}) == 20


def test_ledger_binds_closure_head_column_to_merged_pr_column_by_position() -> None:
    rows = _finding_rows(LEDGER)
    expected = _expected_by_finding()

    assert set(expected) == {
        "F-017",
        "F-019",
        "F-032",
        "F-033",
        "F-034",
        "F-035",
        "F-036",
        "F-037",
        "F-038",
        "F-039",
        "F-040",
        "F-041",
        "F-042",
    }
    for finding, expected_pairs in expected.items():
        row = rows[finding]
        assert row[2] == "Merged and independently closed"
        closure_heads = SHA_RE.findall(row[7])
        merged_prs = [int(value) for value in PR_RE.findall(row[8])]
        assert list(zip(closure_heads, merged_prs, strict=True)) == expected_pairs
        assert "Pending" not in " | ".join(row)


def test_reconciliation_preserves_scope_and_programme_identity() -> None:
    ledger = LEDGER.read_text(encoding="utf-8")
    closure_map = CLOSURE_MAP.read_text(encoding="utf-8")
    normalized_map = " ".join(closure_map.split())

    assert "finding index, not a live approval" in ledger
    assert "PR-12 through PR-14 remain planned" in normalized_map
    assert "Calculation-trace retirement is reconciled separately" in normalized_map
    assert "Removed trace files and surfaces are not evidence" in normalized_map
    assert sector.__version__ == "0.92"
