from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import get_type_hints

import pytest

from tools.manual_current_schema_statements import (
    CURRENT_PROJECT_SAVE_WORDING,
    current_schema_wording,
    validate_current_manual_schema_statements,
)


class _IntSubclass(int):
    pass


class _ContainsEverything(str):
    def __contains__(self, item: object) -> bool:
        return True


def _manual_text(*, project_schema: int = 25) -> str:
    return "\n".join(
        (
            "Sector user manual",
            current_schema_wording(project_schema),
            CURRENT_PROJECT_SAVE_WORDING,
        )
    )


def test_current_schema_statements_have_literal_oracles() -> None:
    assert current_schema_wording(25) == "Current projects use schema version 25"
    assert current_schema_wording(26) == "Current projects use schema version 26"
    assert (
        CURRENT_PROJECT_SAVE_WORDING
        == "Every downloaded project save uses the current schema"
    )


@pytest.mark.parametrize("project_schema", [25, 26])
def test_current_manual_schema_statements_accept_each_supplied_identity(
    project_schema: int,
) -> None:
    validate_current_manual_schema_statements(
        _manual_text(project_schema=project_schema),
        project_schema=project_schema,
    )


@pytest.mark.parametrize(
    "project_schema",
    [None, True, False, 0, -1, 25.0, "25", _IntSubclass(25)],
)
def test_current_manual_schema_statements_reject_malformed_schema_input(
    project_schema: object,
) -> None:
    with pytest.raises(AssertionError, match="positive integer"):
        validate_current_manual_schema_statements(
            _manual_text(),
            project_schema=project_schema,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "flat_text",
    [None, 25, b"manual", [], {}, _ContainsEverything("")],
)
def test_current_manual_schema_statements_reject_nontext_content(
    flat_text: object,
) -> None:
    with pytest.raises(AssertionError, match="must be text"):
        validate_current_manual_schema_statements(flat_text, project_schema=25)


@pytest.mark.parametrize(
    "missing_statement",
    [
        "Current projects use schema version 25",
        "Every downloaded project save uses the current schema",
    ],
)
def test_current_manual_schema_statements_require_each_literal(
    missing_statement: str,
) -> None:
    text = _manual_text().replace(missing_statement, "")
    with pytest.raises(AssertionError, match="expected manual content is missing"):
        validate_current_manual_schema_statements(text, project_schema=25)


@pytest.mark.parametrize(
    ("exact_statement", "near_miss"),
    [
        (
            "Current projects use schema version 25",
            "current projects use schema version 25",
        ),
        (
            "Current projects use schema version 25",
            "Current  projects use schema version 25",
        ),
        (
            "Current projects use schema version 25",
            "Current projects use schema: version 25",
        ),
        (
            "Every downloaded project save uses the current schema",
            "every downloaded project save uses the current schema",
        ),
        (
            "Every downloaded project save uses the current schema",
            "Every downloaded  project save uses the current schema",
        ),
        (
            "Every downloaded project save uses the current schema",
            "Every downloaded project uses the current schema",
        ),
    ],
)
def test_current_manual_schema_statements_reject_literal_near_misses(
    exact_statement: str,
    near_miss: str,
) -> None:
    text = _manual_text().replace(exact_statement, near_miss)
    with pytest.raises(AssertionError, match="expected manual content is missing"):
        validate_current_manual_schema_statements(text, project_schema=25)


@pytest.mark.parametrize(
    "unowned_text",
    [
        "Schema 24",
        "Schema: version 24",
        '"schema version": 24',
        "Sector v0.93",
        "Sector version 0.93",
        "Sector release 0.93",
        "v0.93",
        "Previous schema behaviour is documented elsewhere.",
        "Schema behaviour from an earlier practice is not discussed here.",
        "Legacy square-root branch",
        "The plane-section assumption no longer holds.",
    ],
)
def test_current_manual_schema_statements_ignore_unowned_text(
    unowned_text: str,
) -> None:
    validate_current_manual_schema_statements(
        _manual_text() + "\n" + unowned_text,
        project_schema=25,
    )


def test_current_manual_schema_statements_have_required_signature() -> None:
    signature = inspect.signature(validate_current_manual_schema_statements)
    parameters = tuple(signature.parameters.values())
    assert tuple(parameter.name for parameter in parameters) == (
        "flat_text",
        "project_schema",
    )
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[0].default is inspect.Parameter.empty
    assert parameters[1].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[1].default is inspect.Parameter.empty
    type_hints = get_type_hints(validate_current_manual_schema_statements)
    assert type_hints == {
        "flat_text": object,
        "project_schema": int,
        "return": type(None),
    }


def test_current_schema_wording_has_required_signature() -> None:
    signature = inspect.signature(current_schema_wording)
    parameters = tuple(signature.parameters.values())
    assert tuple(parameter.name for parameter in parameters) == ("project_schema",)
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[0].default is inspect.Parameter.empty
    assert get_type_hints(current_schema_wording) == {
        "project_schema": int,
        "return": str,
    }


def test_current_manual_schema_statements_module_has_no_scanner_dependency() -> None:
    module_path = Path(inspect.getfile(validate_current_manual_schema_statements))
    module_tree = ast.parse(module_path.read_text(encoding="utf-8"))
    assert not any(
        (
            isinstance(node, ast.Import)
            and any(alias.name == "re" for alias in node.names)
        )
        or (isinstance(node, ast.ImportFrom) and node.module == "re")
        for node in ast.walk(module_tree)
    )
