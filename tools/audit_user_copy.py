"""Inventory user-facing copy in the Streamlit app, manual, and reports.

The inventory is a review aid, not a prose-quality verdict. Long text and
negative wording are useful triage signals, but safety boundaries and
fail-closed calculation reasons often need them. Reviewers must classify each
candidate by its task value before changing it.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
SECTOR = ROOT / "sector"

FIRST_ARGUMENT_SURFACES = {
    "button",
    "caption",
    "checkbox",
    "data_editor",
    "dialog",
    "download_button",
    "error",
    "expander",
    "header",
    "info",
    "markdown",
    "metric",
    "multiselect",
    "number_input",
    "popover",
    "radio",
    "segmented_control",
    "selectbox",
    "slider",
    "status",
    "subheader",
    "success",
    "tabs",
    "text_area",
    "text_input",
    "title",
    "toast",
    "toggle",
    "warning",
    "write",
    "_p",
    "_small",
    "_h1",
    "_h2",
    "_h3",
    "md",
}
TABLE_SURFACES = {
    "_table",
    "table",
}
USER_COPY_KEYWORDS = {
    "alternative",
    "caption",
    "description",
    "detail",
    "disclosure",
    "error",
    "guidance",
    "help",
    "label",
    "message",
    "note",
    "reason",
    "ref",
    "reference",
    "scope",
    "statement",
    "title",
    "verdict",
    "warning",
}
ASSIGNMENT_COPY_NAME_TOKENS = tuple(USER_COPY_KEYWORDS)
REGISTRY_NAME_TOKENS = (
    "DESCRIPTION",
    "DISCLOSURE",
    "ERROR",
    "GUIDANCE",
    "HELP",
    "LABEL",
    "MESSAGE",
    "META",
    "NOTE",
    "REASON",
    "SOURCE",
    "TITLE",
    "WARNING",
)
NEGATIVE_TOKENS = (
    " not ",
    " no ",
    "do not",
    "does not",
    "cannot",
    "isn't",
    "aren't",
    "never",
    "without",
    "rather than",
    "instead of",
)
DEVELOPER_TOKENS = (
    " sha ",
    "sha-",
    "sha256",
    "hash",
    "payload",
    "dispatch",
    "canonical",
    "internal identifier",
    "inventory",
    "capability binding",
    "kernel",
    "fallback",
    "contract",
    "provenance",
    "stable key",
    "basis key",
    "solver edition",
    "source revision",
    "source version",
    "input snapshot",
    "solver binding",
    "registered basis",
    "retained result",
    " retained ",
    " retains ",
    "authoritative output",
    "semantic check",
    "schema",
    " solver ",
    "solver-state",
    "solver state",
    "solver target",
    "stable identity",
    "stable identifier",
    " stable ",
    " identity ",
    " authoritative ",
    "table-owned",
    " metadata ",
    " migration ",
    " legacy ",
    " fallback ",
    "implementation",
)

STRUCTURED_COPY_CALLS = {
    "WarningReference",
    "Workflow",
}
EQUATION_COPY_CALLS = {
    "_relation",
    "_result",
}
RETURN_COPY_FILES = {
    "case_analysis.py",
    "fatigue_presentation.py",
    "heightened_crack_adapter.py",
    "input_issues.py",
    "material_catalog.py",
    "project_io.py",
    "report_profiles.py",
    "result_presentation.py",
}


def developer_terms(text: str) -> tuple[str, ...]:
    """Return development-process terms found in normalized visible text."""

    compact = " ".join(text.split())
    words = " " + re.sub(r"[^a-z0-9]+", " ", compact.casefold()).strip() + " "
    found = []
    if re.search(r"\bEQ-[A-Z0-9][A-Z0-9._-]*\b", compact):
        found.append("internal equation identifier")
    for token in DEVELOPER_TOKENS:
        normalized = re.sub(r"[^a-z0-9]+", " ", token.casefold()).strip()
        label = token.strip()
        if normalized and f" {normalized} " in words and label not in found:
            found.append(label)
    return tuple(found)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _module_bindings(tree: ast.Module) -> dict[str, ast.AST]:
    bindings: dict[str, ast.AST] = {}
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            value = statement.value
            for target in targets:
                if isinstance(target, ast.Name) and value is not None:
                    bindings[target.id] = value
    return bindings


def _literal_text(
    node: ast.AST | None,
    bindings: dict[str, ast.AST],
    seen: frozenset[str] = frozenset(),
) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in bindings and node.id not in seen:
            return _literal_text(
                bindings[node.id], bindings, seen | {node.id}
            )
        return ""
    if isinstance(node, ast.JoinedStr):
        return "".join(
            value.value
            if isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            else "{...}"
            for value in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_text(node.left, bindings, seen) + _literal_text(
            node.right, bindings, seen
        )
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return " | ".join(
            _literal_text(value, bindings, seen) for value in node.elts
        )
    if isinstance(node, ast.Dict):
        return " | ".join(
            value
            for key, item in zip(node.keys, node.values)
            for value in (
                _literal_text(key, bindings, seen),
                _literal_text(item, bindings, seen),
            )
            if value
        )
    if isinstance(node, ast.IfExp):
        return " | ".join(
            value
            for value in (
                _literal_text(node.body, bindings, seen),
                _literal_text(node.orelse, bindings, seen),
            )
            if value
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in {"format", "replace", "strip"}:
            return _literal_text(node.func.value, bindings, seen)
    return ""


def _is_internal_key_collection(node: ast.AST | None) -> bool:
    """Recognize tuples/lists of program keys that are not visible prose."""

    if isinstance(node, ast.Dict) and node.keys:
        items = node.keys
    elif isinstance(node, (ast.List, ast.Set, ast.Tuple)) and node.elts:
        items = node.elts
    else:
        return False
    return all(
        isinstance(item, ast.Constant)
        and isinstance(item.value, str)
        and re.fullmatch(r"[a-z0-9_]+", item.value) is not None
        for item in items
    )


def _surface_row(
    *, path: Path, line: int, surface: str, text: str
) -> dict[str, Any] | None:
    compact = " ".join(text.split())
    if not compact:
        return None
    lowered = f" {compact.casefold()} "
    return {
        "file": path.relative_to(ROOT).as_posix(),
        "line": line,
        "surface": surface,
        "characters": len(compact),
        "words": len(compact.split()),
        "negative_tokens": [
            token.strip()
            for token in NEGATIVE_TOKENS
            if token in lowered
        ],
        "developer_tokens": list(developer_terms(compact)),
        "text": compact,
    }


def inventory_file(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bindings = _module_bindings(tree)
    module_statement_ids = {id(statement) for statement in tree.body}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()

    def append(line: int, surface: str, value: ast.AST | None) -> None:
        row = _surface_row(
            path=path,
            line=line,
            surface=surface,
            text=_literal_text(value, bindings),
        )
        if row is None:
            return
        identity = (line, surface, row["text"])
        if identity not in seen:
            seen.add(identity)
            rows.append(row)

    def append_registry(
        line: int, surface: str, value: ast.AST | None
    ) -> None:
        if isinstance(value, ast.Dict):
            for index, (key, item) in enumerate(
                zip(value.keys, value.values), start=1
            ):
                key_text = " ".join(_literal_text(key, bindings).split())
                suffix = key_text or str(index)
                append(
                    getattr(item, "lineno", line),
                    f"{surface}[{suffix}]",
                    item,
                )
            return
        if isinstance(value, (ast.List, ast.Set, ast.Tuple)):
            for index, item in enumerate(value.elts, start=1):
                append(
                    getattr(item, "lineno", line),
                    f"{surface}[{index}]",
                    item,
                )
            return
        append(line, surface, value)

    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            registry_name = target.id.lstrip("_")
            if not registry_name.isupper() or not any(
                token in registry_name for token in REGISTRY_NAME_TOKENS
            ):
                continue
            append_registry(
                statement.lineno,
                f"registry_{target.id.casefold()}",
                statement.value,
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in FIRST_ARGUMENT_SURFACES and node.args:
                append(node.lineno, name, node.args[0])
            if name in TABLE_SURFACES and node.args:
                table_args = node.args[:2] if name == "table" else node.args[:1]
                for index, value in enumerate(table_args, start=1):
                    append(node.lineno, f"{name}_content_{index}", value)
            if name == "call" and len(node.args) >= 2:
                append(node.lineno, "manual_callout", node.args[1])
            if name == "_manual_warning" and len(node.args) >= 3:
                append(node.lineno, "warning", node.args[2])
            if name == "fig" and len(node.args) >= 3:
                append(node.lineno, "manual_figure_caption", node.args[1])
                append(node.lineno, "manual_figure_alternative", node.args[2])
            if name == "_source" and len(node.args) >= 5:
                append(node.lineno, "manual_equation_source", node.args[4])
            if name in STRUCTURED_COPY_CALLS:
                for index, value in enumerate(node.args, start=1):
                    append(
                        node.lineno,
                        f"{name.casefold()}_{index}",
                        value,
                    )
            if (
                path.name == "table_field_definitions.py"
                and name == "_field"
            ):
                for index, value in enumerate(node.args, start=1):
                    append(node.lineno, f"field_copy_{index}", value)
            if (
                path.name == "report_equation_contract.py"
                and name in EQUATION_COPY_CALLS
            ):
                for index, value in enumerate(node.args, start=1):
                    append(node.lineno, f"equation_copy_{index}", value)
            for keyword in node.keywords:
                if keyword.arg in USER_COPY_KEYWORDS:
                    append(node.lineno, str(keyword.arg), keyword.value)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            if id(node) in module_statement_ids:
                continue
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
            )
            for target in targets:
                if not isinstance(target, ast.Name) or not any(
                    token in target.id.casefold()
                    for token in ASSIGNMENT_COPY_NAME_TOKENS
                ):
                    continue
                append(
                    node.lineno,
                    f"assigned_{target.id}",
                    node.value,
                )
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value in USER_COPY_KEYWORDS
                ):
                    append(node.lineno, f"mapping_{key.value}", value)
        elif isinstance(node, ast.Return):
            if path.name == "table_field_definitions.py":
                append(node.lineno, "field_rule", node.value)
            elif (
                path.name in RETURN_COPY_FILES
                and not _is_internal_key_collection(node.value)
            ):
                append(node.lineno, "returned_copy", node.value)

    rows.sort(key=lambda row: (row["line"], row["surface"], row["text"]))
    return rows


def build_inventory() -> list[dict[str, Any]]:
    rows = [
        row
        for path in sorted((*APP.glob("*.py"), *SECTOR.glob("*.py")))
        for row in inventory_file(path)
    ]
    rows.sort(key=lambda row: (row["file"], row["line"], row["surface"]))
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def manual_file(row: dict[str, Any]) -> bool:
        return row["file"].startswith("app/manual")

    by_domain = {
        "streamlit_and_helpers": sum(
            not manual_file(row) and row["file"] != "app/sector_report.py"
            for row in rows
        ),
        "manual": sum(manual_file(row) for row in rows),
        "report": sum(
            row["file"] == "app/sector_report.py" for row in rows
        ),
    }
    return {
        "surfaces": len(rows),
        "domains": by_domain,
        "over_40_words": sum(row["words"] > 40 for row in rows),
        "over_60_words": sum(row["words"] > 60 for row in rows),
        "negative_candidates": sum(bool(row["negative_tokens"]) for row in rows),
        "developer_candidates": sum(
            bool(row["developer_tokens"]) for row in rows
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--candidates", type=Path)
    args = parser.parse_args(argv)

    rows = build_inventory()
    result = {"summary": summary(rows), "surfaces": rows}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if args.candidates:
        candidates = [
            row
            for row in rows
            if (
                row["words"] > 40
                or row["negative_tokens"]
                or row["developer_tokens"]
            )
        ]
        args.candidates.parent.mkdir(parents=True, exist_ok=True)
        args.candidates.write_text(
            json.dumps(candidates, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps(summary(rows), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
