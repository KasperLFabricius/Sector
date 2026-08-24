from __future__ import annotations

import ast
import re
from pathlib import Path

from tools.crack_publication_wording import retired_crack_wording_rules


_ROOT = Path(__file__).resolve().parents[1]
_PYTHON_PUBLICATION_FILES = (
    "app/case_analysis.py",
    "app/heightened_crack_adapter.py",
    "app/input_issues.py",
    "app/load_cases.py",
    "app/manual.py",
    "app/manual_information_architecture.py",
    "app/project_io.py",
    "app/reproducible_example.py",
    "app/result_presentation.py",
    "app/sector_app.py",
    "app/sector_report.py",
    "sector/sls.py",
    "sector/sls_identity.py",
)
_MARKDOWN_PUBLICATION_FILES = ("README.md", "docs/product_identity.md")

_RETIRED_LITERAL_FRAGMENTS = (
    "if no criterion is entered",
    "with no criterion",
    "without a criterion",
    "one optional positive permitted width",
    "one optional permitted width in analysis settings",
    "the optional permitted crack width in analysis settings is blank",
    "permitted crack width $w_k$ (mm, optional)",
    "shared user-specified permitted crack width",
    "leave blank to calculate",
    "global permitted crack width",
    "permitted crack width is shared",
    "shared permitted crack-width",
)

_REQUIRED_CURRENT_FRAGMENTS = (
    "long-term limit $w_{k,long}$ (mm; 0 = no comparison)",
    "short-term limit $w_{k,short}$ (mm; 0 = no comparison)",
    "formula 7.100 na is a separate section-level calculation",
    "duration-matched user comparisons; zero means no comparison",
)

_RETIRED_REFERENCE_PASSAGES = (
    "If no criterion is entered, the width is only stated.",
    "With no criterion the crack-width result remains numerical.",
    "Without a criterion, optional crack width is a numerical output.",
    "One optional positive permitted width is supplied in Analysis settings.",
    "One optional permitted width in Analysis settings is shared.",
    "The optional permitted crack width in Analysis settings is blank.",
    r"Permitted crack width $w_k$ (mm, optional)",
    "Shared user-specified permitted crack width. Leave blank to calculate.",
    "Global permitted crack width",
    "The permitted crack width is shared from Analysis settings.",
    "The shared permitted crack-width setting",
)


def _python_strings(relative_path: str) -> tuple[tuple[int, str], ...]:
    source = (_ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=relative_path)
    return tuple(
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _markdown_paragraphs(relative_path: str) -> tuple[tuple[int, str], ...]:
    source = (_ROOT / relative_path).read_text(encoding="utf-8")
    return tuple(
        (index, paragraph)
        for index, paragraph in enumerate(re.split(r"\n\s*\n", source), start=1)
        if paragraph.strip()
    )


def _publication_passages() -> tuple[tuple[str, int, str], ...]:
    passages: list[tuple[str, int, str]] = []
    for relative_path in _PYTHON_PUBLICATION_FILES:
        for line, value in _python_strings(relative_path):
            passages.append((relative_path, line, value))
    for relative_path in _MARKDOWN_PUBLICATION_FILES:
        for paragraph, value in _markdown_paragraphs(relative_path):
            passages.append((relative_path, paragraph, value))
    return tuple(passages)


def test_current_crack_publication_surfaces_use_no_shared_limit_language() -> None:
    violations: list[tuple[str, int, tuple[str, ...], str]] = []
    for relative_path, line, value in _publication_passages():
        rules = retired_crack_wording_rules(value)
        if rules:
            violations.append((relative_path, line, rules, value))

    assert violations == []


def test_current_crack_publication_surfaces_replace_exact_retired_phrases() -> None:
    violations: list[tuple[str, int, str, str]] = []
    normalized_passages: list[str] = []
    for relative_path, line, value in _publication_passages():
        normalized = " ".join(value.split()).lower()
        normalized_passages.append(normalized)
        for fragment in _RETIRED_LITERAL_FRAGMENTS:
            if fragment in normalized:
                violations.append((relative_path, line, fragment, value))

    assert violations == []

    corpus = "\n".join(normalized_passages)
    assert all(fragment in corpus for fragment in _REQUIRED_CURRENT_FRAGMENTS)


def test_exact_retired_phrase_inventory_is_mutation_resistant() -> None:
    normalized_samples = (
        " ".join(passage.split()).lower()
        for passage in _RETIRED_REFERENCE_PASSAGES
    )
    detected = {
        fragment
        for passage in normalized_samples
        for fragment in _RETIRED_LITERAL_FRAGMENTS
        if fragment in passage
    }
    assert detected == set(_RETIRED_LITERAL_FRAGMENTS)
