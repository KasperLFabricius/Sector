"""Direct controls for the dormant current-manual identity contract."""

from __future__ import annotations

import inspect

import pytest

from tools import manual_current_identity

_SCHEMA_25_WORDING = "Current projects use schema version 25"
_CURRENT_SAVE_WORDING = "Every downloaded project save uses the current schema"


def _current_text(*extra: str, schema: int = 25, product: str = "0.94") -> str:
    return ". ".join(
        (
            f"Current projects use schema version {schema}",
            _CURRENT_SAVE_WORDING,
            f"Sector v{product} - user manual",
            *extra,
        )
    )


def _validate(
    text: object,
    *,
    schema: int = 25,
    product: str = "0.94",
) -> None:
    manual_current_identity.validate_current_manual_identity(
        text,
        project_schema=schema,
        product_version=product,
    )


def test_current_manual_identity_uses_literal_current_sentences():
    assert manual_current_identity.current_schema_wording(25) == (
        _SCHEMA_25_WORDING
    )
    assert manual_current_identity.CURRENT_PROJECT_SAVE_WORDING == (
        _CURRENT_SAVE_WORDING
    )


@pytest.mark.parametrize(
    ("schema", "product"),
    ((25, "0.94"), (26, "0.95")),
)
def test_current_manual_identity_accepts_each_supplied_identity(
    schema,
    product,
):
    _validate(
        _current_text(
            f"Schema v{schema}",
            f"Sector version {product}",
            f"Sector release {product}",
            f"v{product}",
            schema=schema,
            product=product,
        ),
        schema=schema,
        product=product,
    )


@pytest.mark.parametrize(
    "missing",
    (_SCHEMA_25_WORDING, _CURRENT_SAVE_WORDING),
)
def test_current_manual_identity_requires_both_literal_statements(missing):
    with pytest.raises(AssertionError, match="expected manual content is missing"):
        _validate(_current_text().replace(missing, ""))


def test_current_manual_identity_requires_one_current_product_reference():
    with pytest.raises(AssertionError, match="current Sector product version"):
        _validate(_current_text().replace("Sector v0.94 - user manual", ""))


def test_current_manual_identity_accepts_current_product_with_punctuation():
    text = _current_text().replace(
        "Sector v0.94 - user manual",
        'Current product: "Sector version v0.94".',
    )
    _validate(text)


@pytest.mark.parametrize("malformed", (None, b"manual", 25, object()))
def test_current_manual_identity_rejects_non_text(malformed):
    with pytest.raises(AssertionError, match="must be text"):
        _validate(malformed)


@pytest.mark.parametrize("project_schema", (None, True, 0, -1, 25.0, "25"))
def test_current_manual_identity_rejects_malformed_schema_input(
    project_schema,
):
    with pytest.raises(AssertionError, match="positive integer"):
        manual_current_identity.validate_current_manual_identity(
            _current_text(),
            project_schema=project_schema,
            product_version="0.94",
        )


@pytest.mark.parametrize(
    "product_version",
    (
        None,
        b"0.94",
        "",
        "v0.94",
        "0.94-beta",
        "94",
        "\u0660.\u0669\u0664",
    ),
)
def test_current_manual_identity_rejects_malformed_product_version_input(
    product_version,
):
    with pytest.raises(AssertionError, match="ASCII dotted number"):
        manual_current_identity.validate_current_manual_identity(
            _current_text(),
            project_schema=25,
            product_version=product_version,
        )


@pytest.mark.parametrize(
    "non_current",
    (
        "Schema 24",
        "schema version 24",
        "SCHEMA VERSION 23",
        "schema v24",
        "Schema 26",
        "schema v25-beta",
        "schema v25.beta",
        "schema v25beta",
        "schema v\u0662\u0665",
    ),
)
def test_current_manual_identity_rejects_lower_higher_and_qualified_schema(
    non_current,
):
    with pytest.raises(AssertionError, match="non-current schema"):
        _validate(_current_text(non_current))


@pytest.mark.parametrize(
    "non_current",
    (
        "Sector v0.93",
        "Sector version 0.93",
        "Sector release 0.93",
        "sector 0.92",
        "v0.93",
        "Sector v0.95",
        "v0.95",
        "Sector v0.94-beta",
        "v0.94+build",
        "Sector v0.94beta",
        "Sector v0.94.beta",
        "Sector v0.94\u03b2",
        "v0.94_rc1",
        "Sector v0.94/compat",
    ),
)
def test_current_manual_identity_rejects_other_or_qualified_product_tokens(
    non_current,
):
    with pytest.raises(AssertionError, match="non-current Sector version"):
        _validate(_current_text(non_current))


def test_current_manual_identity_uses_required_signature():
    parameters = tuple(
        inspect.signature(
            manual_current_identity.validate_current_manual_identity
        ).parameters.values()
    )
    assert tuple(parameter.name for parameter in parameters) == (
        "flat_text",
        "project_schema",
        "product_version",
    )
    assert parameters[0].default is inspect.Parameter.empty
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(
        parameter.default is inspect.Parameter.empty
        and parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in parameters[1:]
    )
