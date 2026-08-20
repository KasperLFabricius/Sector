from __future__ import annotations

import inspect

import pytest

from tools.manual_current_schema import (
    CURRENT_PROJECT_SAVE_WORDING,
    current_schema_wording,
    validate_current_manual_schema,
)


def _manual_text(*, project_schema: int = 25) -> str:
    return "\n".join(
        (
            "Sector user manual",
            current_schema_wording(project_schema),
            CURRENT_PROJECT_SAVE_WORDING,
            "Sector v0.94",
        )
    )


def test_current_schema_wording_has_literal_current_only_oracles() -> None:
    assert current_schema_wording(25) == "Current projects use schema version 25"
    assert current_schema_wording(26) == "Current projects use schema version 26"
    assert (
        CURRENT_PROJECT_SAVE_WORDING
        == "Every downloaded project save uses the current schema"
    )


@pytest.mark.parametrize("project_schema", [25, 26])
def test_current_manual_schema_accepts_each_supplied_identity(
    project_schema: int,
) -> None:
    validate_current_manual_schema(
        _manual_text(project_schema=project_schema),
        project_schema=project_schema,
    )


@pytest.mark.parametrize(
    "visible_reference",
    [
        "Schema 25.",
        '"Schema 25"',
        "(Schema version 25)",
        "Schema version: 25",
        "Schema: version 25",
        "Schema: version v25",
        "Schema: v25;",
        "Schema-25",
        "Schema-v25",
        "Schema-version-25",
        "Schema-version-v25",
        '"schema": 25',
        "'schema': 25",
        "Schema #25",
        "Schema = 25",
        'Schema: "25"',
        'Schema: "v25"',
        "Schema: '25'",
        "Schema: 'v25'",
        '"schema": "v25"',
        'Schema: "version 25"',
        '"schema": \'version 25\'',
        'Schema version "25"',
        'Schema version "v25"',
        "Schema version '25'",
        "Schema version 'v25'",
        "Schema version = 25",
        "Schema version #25",
    ],
)
def test_current_manual_schema_accepts_current_reference_punctuation(
    visible_reference: str,
) -> None:
    validate_current_manual_schema(
        _manual_text() + "\n" + visible_reference,
        project_schema=25,
    )


@pytest.mark.parametrize(
    "project_schema",
    [None, True, False, 0, -1, 25.0, "25"],
)
def test_current_manual_schema_rejects_malformed_schema_input(
    project_schema: object,
) -> None:
    with pytest.raises(AssertionError, match="positive integer"):
        validate_current_manual_schema(
            _manual_text(),
            project_schema=project_schema,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("flat_text", [None, 25, b"manual", [], {}])
def test_current_manual_schema_rejects_nontext_content(flat_text: object) -> None:
    with pytest.raises(AssertionError, match="must be text"):
        validate_current_manual_schema(flat_text, project_schema=25)


@pytest.mark.parametrize(
    "missing_text",
    [
        "Current projects use schema version 25",
        "Every downloaded project save uses the current schema",
    ],
)
def test_current_manual_schema_requires_each_literal_statement(
    missing_text: str,
) -> None:
    text = _manual_text().replace(missing_text, "")
    with pytest.raises(AssertionError, match="expected manual content is missing"):
        validate_current_manual_schema(text, project_schema=25)


@pytest.mark.parametrize("version", [24, 26])
@pytest.mark.parametrize(
    "template",
    [
        "Schema {}",
        "Schema version {}",
        "Schema version: {}",
        "Schema: {}",
        "Schema: version {}",
        "Schema v{}",
        "Schema version v{}",
        "Schema: v{}",
        "Schema: version v{}",
        "Schema-{}",
        "Schema-v{}",
        "Schema-version-{}",
        "Schema-version-v{}",
        '"schema": {}',
        "'schema': {}",
        "Schema #{}",
        "Schema = {}",
        'Schema: "{}"',
        'Schema: "v{}"',
        "Schema: '{}'",
        "Schema: 'v{}'",
        '"schema": "v{}"',
        'Schema: "version {}"',
        '"schema": \'version {}\'',
        'Schema version "{}"',
        'Schema version "v{}"',
        "Schema version '{}'",
        "Schema version 'v{}'",
        "Schema version = {}",
        "Schema version #{}",
    ],
)
def test_current_manual_schema_rejects_each_noncurrent_reference_form(
    template: str,
    version: int,
) -> None:
    with pytest.raises(AssertionError, match="non-current schema references"):
        validate_current_manual_schema(
            _manual_text() + "\n" + template.format(version),
            project_schema=25,
        )


@pytest.mark.parametrize(
    "visible_reference",
    [
        "Schema 25beta",
        "Schema 25-beta",
        "Schema 25+build",
        "Schema 25_legacy",
        "Schema 25/legacy",
        "Schema 25β",
        'Schema: "v25-beta"',
        'Schema: "version v25-beta"',
        "Schema: 'v25-beta'",
        "Schema version 'v25-beta'",
    ],
)
def test_current_manual_schema_rejects_qualified_current_identity(
    visible_reference: str,
) -> None:
    with pytest.raises(AssertionError, match="non-current schema references"):
        validate_current_manual_schema(
            _manual_text() + "\n" + visible_reference,
            project_schema=25,
        )


@pytest.mark.parametrize(
    "product_identity",
    [
        "Version 0.93",
        "Sector v0.93",
        "Sector version 0.95",
        "Sector release 1.0",
        "v0.93",
        "Sector v0.94-beta",
    ],
)
def test_current_manual_schema_ignores_product_identity(
    product_identity: str,
) -> None:
    validate_current_manual_schema(
        _manual_text() + "\n" + product_identity,
        project_schema=25,
    )


@pytest.mark.parametrize(
    "historical_prose",
    [
        "Previous schema behaviour is documented elsewhere.",
        "Schema behaviour from an earlier practice is not discussed here.",
        "Legacy square-root branch",
        "The plane-section assumption no longer holds.",
    ],
)
def test_current_manual_schema_ignores_historical_prose(
    historical_prose: str,
) -> None:
    validate_current_manual_schema(
        _manual_text() + "\n" + historical_prose,
        project_schema=25,
    )


@pytest.mark.parametrize(
    "embedded_identifier",
    ["dataschema-24", "x_schema-26", "myschema: version 24"],
)
def test_current_manual_schema_ignores_embedded_schema_identifiers(
    embedded_identifier: str,
) -> None:
    validate_current_manual_schema(
        _manual_text() + "\n" + embedded_identifier,
        project_schema=25,
    )


def test_current_manual_schema_has_one_required_keyword_only_identity() -> None:
    signature = inspect.signature(validate_current_manual_schema)
    parameters = tuple(signature.parameters.values())
    assert tuple(parameter.name for parameter in parameters) == (
        "flat_text",
        "project_schema",
    )
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[0].default is inspect.Parameter.empty
    assert parameters[1].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[1].default is inspect.Parameter.empty
