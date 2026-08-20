from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "pr_a04b1a_v095_crack_request_contract.md"


def _contract_text() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def test_crack_request_contract_freezes_the_independent_action_gate() -> None:
    text = " ".join(_contract_text().split())
    for required in (
        "438cf70bc9d4865ca10abb00af29537c7b905e67",
        "Each Elastic action owns `calculate_crack_width` independently",
        "`calculate_crack_width is False`",
        "`NOT REQUESTED`",
        "including `0 mm` or a positive value",
        "never turns the per-action request on",
        "Only when `calculate_crack_width is True`",
        "state the matching duration width without comparison",
        "the action-table `calculate_crack_width` identity and default-off behavior",
        "project-level limits as comparison inputs only, never request inputs",
        "No retired-language inventory",
        "No schema migration or dual-duration result activation",
    ):
        assert required in text


def test_crack_request_contract_covers_every_request_limit_pair() -> None:
    text = _contract_text()
    for row in (
        "| A04b1a-01 | False | 0 mm | `NOT REQUESTED`; no width or comparison. |",
        "| A04b1a-02 | False | Positive | `NOT REQUESTED`; the positive value does not request a calculation. |",
        "| A04b1a-03 | True | 0 mm | Width may be calculated and stated without comparison. |",
        "| A04b1a-04 | True | Positive | Width may be calculated and compared only with the matching duration limit. |",
        "| A04b1a-05 | Different Elastic rows use different request flags | Any | Each row follows only its own flag. |",
    ):
        assert row in text
