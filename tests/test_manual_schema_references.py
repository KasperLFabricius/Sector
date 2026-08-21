from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

from tools.manual_schema_references import (
    validate_no_noncurrent_manual_schema_references,
)


_REFERENCE_TEMPLATES = (
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
    '"schema version": {}',
    '"schema version": "v{}"',
    "'schema version': 'v{}'",
    '"schema-version": {}',
    'Schema "version": {}',
    'Schema: "version": {}',
    "Schema:version{}",
    "Schema-version{}",
    "Schema version{}",
    "\u201cschema version\u201d: {}",
    "Schema: \u201c{}\u201d",
    "\u2018schema version\u2019: {}",
    "\u00abschema version\u00bb: {}",
    "\u201eschema version\u201f: {}",
    "\u2039schema version\u203a: {}",
    "\u00bbSchema {}\u00ab",
    "Schema\u00a0{}",
    "Schema\u202fversion\u202f{}",
    "Schema\u2010{}",
    "Schema\u2011{}",
    "Schema\u2012{}",
    "Schema\u2013{}",
    "Schema\u2014{}",
)


class _IntSubclass(int):
    pass


class _ContainsEverything(str):
    def __contains__(self, item: object) -> bool:
        return True


@pytest.mark.parametrize("project_schema", [25, 26])
@pytest.mark.parametrize("template", _REFERENCE_TEMPLATES)
def test_schema_reference_check_accepts_current_identity_in_every_form(
    template: str,
    project_schema: int,
) -> None:
    validate_no_noncurrent_manual_schema_references(
        template.format(project_schema),
        project_schema=project_schema,
    )


@pytest.mark.parametrize("visible_schema", [24, 26])
@pytest.mark.parametrize("template", _REFERENCE_TEMPLATES)
def test_schema_reference_check_rejects_old_and_future_identity_in_every_form(
    template: str,
    visible_schema: int,
) -> None:
    with pytest.raises(AssertionError, match="non-current schema references"):
        validate_no_noncurrent_manual_schema_references(
            template.format(visible_schema),
            project_schema=25,
        )


@pytest.mark.parametrize(
    "current_reference",
    [
        "Schema 25.",
        '"Schema 25"',
        "(Schema version 25)",
        "SCHEMA: VERSION V25;",
        "\u201cSchema 25\u201d",
        "Schema 25\u2026",
        "Schema 25\u3002",
    ],
)
def test_schema_reference_check_accepts_current_punctuation_and_case(
    current_reference: str,
) -> None:
    validate_no_noncurrent_manual_schema_references(
        current_reference,
        project_schema=25,
    )


@pytest.mark.parametrize(
    "qualified_reference",
    [
        "Schema 25beta",
        "Schema 25-beta",
        "Schema 25+build",
        "Schema 25_legacy",
        "Schema 25/legacy",
        "Schema 25\u03b2",
        "Schema \u0662\u0665",
        'Schema: "v25-beta"',
        'Schema: "version v25-beta"',
        "Schema: 'v25-beta'",
        "Schema version 'v25-beta'",
        '"schema version": "v25-beta"',
        "\u201cSchema 25-beta\u201d",
        "Schema\u201125-beta",
    ],
)
def test_schema_reference_check_rejects_qualified_current_identity(
    qualified_reference: str,
) -> None:
    with pytest.raises(AssertionError, match="non-current schema references"):
        validate_no_noncurrent_manual_schema_references(
            qualified_reference,
            project_schema=25,
        )


@pytest.mark.parametrize(
    "unowned_text",
    [
        "",
        "Sector v0.93",
        "Sector version 0.95",
        "Sector release 1.0",
        "v0.93",
        "Previous schema behaviour is documented elsewhere.",
        "Schema behaviour from an earlier practice is not discussed here.",
        "Legacy square-root branch",
        "The plane-section assumption no longer holds.",
        "dataschema-24",
        "x_schema-26",
        "myschema: version 24",
        "JSON Schema 2020-12",
        "OpenAPI Schema 3.1",
        "XML Schema 1.1",
        "XSD-Schema 1.1",
        "json schema 2020-12",
        "Xml Schema 1.1",
        "JSON\u00a0Schema 2020-12",
        "OpenAPI\u202fSchema 3.1",
        "JSON\u2010Schema 2020-12",
        "XML\u2011Schema 1.1",
        "XSD\u2012Schema 1.1",
        "OpenAPI\u2013Schema 3.1",
        "JSON\u2014Schema 2020-12",
        "Every downloaded project save uses the current schema\n2. Project input",
        "Current schema\n24-hour support",
        "Current schema\v24-hour support",
        "Current schema\f24-hour support",
        "Current schema\x8524-hour support",
        "Current schema\u202824-hour support",
        "Current schema\u202924-hour support",
    ],
)
def test_schema_reference_check_ignores_unowned_text(unowned_text: str) -> None:
    validate_no_noncurrent_manual_schema_references(
        unowned_text,
        project_schema=25,
    )


@pytest.mark.parametrize(
    "project_reference",
    [
        "JSON data; Schema 24",
        "JSON\nSchema 24",
        "JSON\vSchema 24",
        "JSON\fSchema 24",
        "JSON\x85Schema 24",
        "JSON\u2028Schema 24",
        "JSON\u2029Schema 24",
        "NotJSON Schema 24",
    ],
)
def test_named_schema_exclusion_is_immediate_and_line_local(
    project_reference: str,
) -> None:
    with pytest.raises(AssertionError, match="non-current schema references"):
        validate_no_noncurrent_manual_schema_references(
            project_reference,
            project_schema=25,
        )


@pytest.mark.parametrize(
    "dash",
    ["-", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014"],
)
@pytest.mark.parametrize(
    "separator_template",
    ["{}", " {}", "{} ", " {} "],
)
def test_named_schema_exclusion_accepts_each_spaced_dash(
    dash: str,
    separator_template: str,
) -> None:
    separator = separator_template.format(dash)
    validate_no_noncurrent_manual_schema_references(
        "JSON" + separator + "Schema 2020-12",
        project_schema=25,
    )


def test_named_schema_exclusion_accepts_nbsp_around_dash() -> None:
    validate_no_noncurrent_manual_schema_references(
        "XML\u00a0\u2011\u00a0Schema 1.1",
        project_schema=25,
    )


@pytest.mark.parametrize(
    "flat_text",
    [None, 25, b"manual", [], {}, _ContainsEverything("")],
)
def test_schema_reference_check_rejects_nontext_content(flat_text: object) -> None:
    with pytest.raises(AssertionError, match="must be text"):
        validate_no_noncurrent_manual_schema_references(
            flat_text,
            project_schema=25,
        )


@pytest.mark.parametrize(
    "project_schema",
    [None, True, False, 0, -1, 25.0, "25", _IntSubclass(25)],
)
def test_schema_reference_check_rejects_malformed_schema_input(
    project_schema: object,
) -> None:
    with pytest.raises(AssertionError, match="positive integer"):
        validate_no_noncurrent_manual_schema_references(
            "Schema 25",
            project_schema=project_schema,  # type: ignore[arg-type]
        )


def test_schema_reference_check_reports_each_distinct_noncurrent_identity() -> None:
    with pytest.raises(AssertionError) as exc_info:
        validate_no_noncurrent_manual_schema_references(
            "Schema 24\nSchema: version 26\nSchema-24",
            project_schema=25,
        )
    assert str(exc_info.value) == (
        "the manual contains non-current schema references: 24, 26"
    )


def test_schema_reference_check_has_required_signature() -> None:
    signature = inspect.signature(validate_no_noncurrent_manual_schema_references)
    parameters = tuple(signature.parameters.values())
    assert tuple(parameter.name for parameter in parameters) == (
        "flat_text",
        "project_schema",
    )
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[0].default is inspect.Parameter.empty
    assert parameters[1].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[1].default is inspect.Parameter.empty
    assert get_type_hints(validate_no_noncurrent_manual_schema_references) == {
        "flat_text": object,
        "project_schema": int,
        "return": type(None),
    }
