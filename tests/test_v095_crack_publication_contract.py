from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "pr_a04b1_v095_crack_publication_contract.md"


def _contract_text() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def test_dual_crack_publication_contract_freezes_required_meaning_and_scope() -> None:
    text = _contract_text()
    for required in (
        "438cf70bc9d4865ca10abb00af29537c7b905e67",
        "independent long-term and short-term",
        "per-action crack-width request remains authoritative",
        "NOT REQUESTED",
        "When crack-width calculation is requested",
        "0 mm",
        "matching duration",
        "Formula 7.100 NA permitted width is a separate input",
        "README.md",
        "app/manual.py",
        "app/manual_information_architecture.py",
        "docs/product_identity.md",
        "app/load_cases.py",
        "Historical decision registers",
        "No schema or project migration",
        "No application, report, manual or README activation",
    ):
        assert required in text


def test_dual_crack_publication_contract_lists_every_retired_phrase() -> None:
    text = _contract_text()
    for retired in (
        "With no criterion",
        "Without a criterion",
        "If no criterion is entered",
        "if a criterion is entered",
        "optional user-specified crack-width criterion",
        "one optional positive permitted width",
        "blank ordinary crack criterion",
        "One optional permitted width in Analysis settings is shared by",
        "shared by every ordinary and heightened crack check",
        "shared Analysis permitted width",
        "supply the shared permitted width",
    ):
        assert f"`{retired}`" in text
