from __future__ import annotations

import ast
import copy
import inspect
from pathlib import Path
from typing import get_type_hints

import pytest

import tools.manual_current_program_statements as program_statements
from tools.manual_current_program_statements import (
    CURRENT_REPORT_METADATA_WORDING,
    CURRENT_RESULT_LABEL_WORDING,
    REPLACED_REPORT_METADATA_WORDING,
    REPLACED_RESULT_FIELD_WORDING,
    validate_current_manual_program_statements,
)


class _ContainsEverything(str):
    def __contains__(self, item: object) -> bool:
        return True


_REPORT_LITERAL = (
    "Report details and publication controls are grouped separately from the "
    "Project input stage."
)
_RESULT_LITERAL = (
    "Report labels identify the physical quantity represented by each result field."
)
_REPLACED_REPORT_LITERAL = (
    "Report details and publication controls are no longer mixed with the "
    "Project input stage."
)
_REPLACED_RESULT_LITERAL = "Legacy result-field names remain for compatibility"


def _manual_text() -> str:
    return (
        f"Sector user manual\n{CURRENT_REPORT_METADATA_WORDING}\n"
        f"{CURRENT_RESULT_LABEL_WORDING}"
    )


def test_current_program_statements_have_literal_oracles() -> None:
    assert CURRENT_REPORT_METADATA_WORDING == _REPORT_LITERAL
    assert CURRENT_RESULT_LABEL_WORDING == _RESULT_LITERAL
    assert REPLACED_REPORT_METADATA_WORDING == _REPLACED_REPORT_LITERAL
    assert REPLACED_RESULT_FIELD_WORDING == _REPLACED_RESULT_LITERAL


def test_current_manual_program_statements_accept_the_owned_text() -> None:
    text = _manual_text()
    before = copy.deepcopy(text)
    validate_current_manual_program_statements(text)
    assert text == before
    assert type(text) is str


@pytest.mark.parametrize(
    "missing_statement",
    [_REPORT_LITERAL, _RESULT_LITERAL],
)
def test_current_manual_program_statements_require_each_literal(
    missing_statement: str,
) -> None:
    text = _manual_text().replace(missing_statement, "")
    with pytest.raises(AssertionError, match="must appear exactly once"):
        validate_current_manual_program_statements(text)


@pytest.mark.parametrize(
    "duplicated_statement",
    [CURRENT_REPORT_METADATA_WORDING, CURRENT_RESULT_LABEL_WORDING],
)
def test_current_manual_program_statements_reject_duplicates(
    duplicated_statement: str,
) -> None:
    text = _manual_text() + "\n" + duplicated_statement
    with pytest.raises(AssertionError, match="must appear exactly once"):
        validate_current_manual_program_statements(text)


@pytest.mark.parametrize(
    ("exact_statement", "near_miss"),
    [
        (
            _REPORT_LITERAL,
            _REPORT_LITERAL.replace("Report", "report", 1),
        ),
        (
            _REPORT_LITERAL,
            _REPORT_LITERAL.replace("grouped separately", "grouped  separately"),
        ),
        (
            _REPORT_LITERAL,
            _REPORT_LITERAL.removesuffix("."),
        ),
        (
            _RESULT_LITERAL,
            _RESULT_LITERAL.replace("Report", "report", 1),
        ),
        (
            _RESULT_LITERAL,
            _RESULT_LITERAL.replace("physical quantity", "physical  quantity"),
        ),
        (
            _RESULT_LITERAL,
            "Report labels identify the represented physical quantity for each result field.",
        ),
    ],
)
def test_current_manual_program_statements_reject_literal_near_misses(
    exact_statement: str,
    near_miss: str,
) -> None:
    text = _manual_text().replace(exact_statement, near_miss)
    with pytest.raises(AssertionError, match="must appear exactly once"):
        validate_current_manual_program_statements(text)


@pytest.mark.parametrize(
    "replaced_statement",
    [_REPLACED_REPORT_LITERAL, _REPLACED_RESULT_LITERAL],
)
def test_current_manual_program_statements_reject_each_replaced_literal(
    replaced_statement: str,
) -> None:
    text = _manual_text() + "\n" + replaced_statement
    with pytest.raises(AssertionError, match="replaced program statement"):
        validate_current_manual_program_statements(text)


@pytest.mark.parametrize(
    "replaced_near_miss",
    [
        _REPLACED_REPORT_LITERAL.replace("Report", "report", 1),
        _REPLACED_REPORT_LITERAL.replace("no longer mixed", "not mixed"),
        _REPLACED_REPORT_LITERAL.removesuffix("."),
        _REPLACED_RESULT_LITERAL.replace("Legacy", "legacy", 1),
        _REPLACED_RESULT_LITERAL.replace("result-field", "result field"),
        _REPLACED_RESULT_LITERAL.replace(
            "remain for compatibility", "remain compatible"
        ),
    ],
)
def test_replaced_program_statement_near_misses_remain_out_of_scope(
    replaced_near_miss: str,
) -> None:
    validate_current_manual_program_statements(
        _manual_text() + "\n" + replaced_near_miss
    )


@pytest.mark.parametrize(
    "unowned_text",
    [
        "Current projects use schema version 25",
        "Sector user manual version 0.94",
        "The plane-section assumption no longer holds across a break.",
        "Loading a project clears earlier results.",
        "Former EN 1992 crack-width criterion.",
    ],
)
def test_current_program_statement_contract_ignores_other_manual_domains(
    unowned_text: str,
) -> None:
    validate_current_manual_program_statements(_manual_text() + "\n" + unowned_text)


@pytest.mark.parametrize(
    "flat_text",
    [None, 25, b"manual", [], {}, _ContainsEverything("")],
)
def test_current_manual_program_statements_reject_nontext_content(
    flat_text: object,
) -> None:
    with pytest.raises(AssertionError, match="must be text"):
        validate_current_manual_program_statements(flat_text)


def test_current_manual_program_statements_have_required_signature() -> None:
    signature = inspect.signature(validate_current_manual_program_statements)
    parameters = tuple(signature.parameters.values())
    assert tuple(parameter.name for parameter in parameters) == ("flat_text",)
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[0].default is inspect.Parameter.empty
    assert get_type_hints(validate_current_manual_program_statements) == {
        "flat_text": object,
        "return": type(None),
    }


def test_current_program_statement_module_is_a_literal_contract() -> None:
    module_path = Path(inspect.getfile(validate_current_manual_program_statements))
    module_tree = ast.parse(module_path.read_text(encoding="utf-8"))
    assert not any(
        (
            isinstance(node, ast.Import)
            and any(alias.name == "re" for alias in node.names)
        )
        or (isinstance(node, ast.ImportFrom) and node.module == "re")
        for node in ast.walk(module_tree)
    )


def test_current_program_statement_module_stays_within_owned_scope() -> None:
    source = inspect.getsource(program_statements).lower()
    for excluded_term in (
        "authority",
        "acceptance",
        "conform",
        "certif",
        "approv",
        "compliance",
        "global pass",
        "global fail",
        "verdict",
        "schema version",
        "sector version",
        "sector release",
    ):
        assert excluded_term not in source
