from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

import tools.manual_product_references as product_references
from tools.manual_product_references import (
    validate_no_noncurrent_manual_product_references,
)


_SECTOR_REFERENCE_TEMPLATES = (
    "Sector {}",
    "Sector v{}",
    "Sector V{}",
    "Sector version {}",
    "Sector version v{}",
    "Sector release {}",
    "Sector release v{}",
    "Sector: {}",
    "Sector: v{}",
    "Sector-{}",
    "Sector-v{}",
    "Sector-version-{}",
    "Sector-version-v{}",
    '"Sector version": "{}"',
    "'Sector release': 'v{}'",
    "Sector\u2010{}",
    "Sector\u2011v{}",
    "Sector\u2012version\u2012{}",
    "Sector\u2013version\u2013v{}",
    "Sector\u2014release\u2014{}",
    "Sector\u00a0v{}",
    "Sector\u202fversion\u202f{}",
    "Sector user manual {}",
    "Sector user manual v{}",
    "Sector user manual version {}",
    "Sector user manual release v{}",
    '"Sector user manual version": "{}"',
)
_BARE_REFERENCE_TEMPLATES = (
    "v{}",
    "V{}",
    '"v{}"',
    "'V{}'",
    "v\u00a0{}",
    "v\u202f{}",
)
_VERSION_LABEL_TEMPLATES = (
    "Version {}",
    "Version: {}",
    "Version v{}",
    "Version: v{}",
    '"Version": "{}"',
    "'Version': 'v{}'",
    "\u201cVersion\u201d: \u201c{}\u201d",
    "\u00abVersion\u00bb: \u00abv{}\u00bb",
    "Version\u00a0{}",
    "Version\u202f:\u202f{}",
)
_REFERENCE_TEMPLATES = (
    *_SECTOR_REFERENCE_TEMPLATES,
    *_BARE_REFERENCE_TEMPLATES,
    *_VERSION_LABEL_TEMPLATES,
)
_HORIZONTAL_SPACES = (
    "\t",
    " ",
    "\u00a0",
    "\u1680",
    "\u2000",
    "\u2001",
    "\u2002",
    "\u2003",
    "\u2004",
    "\u2005",
    "\u2006",
    "\u2007",
    "\u2008",
    "\u2009",
    "\u200a",
    "\u202f",
    "\u205f",
    "\u3000",
)
_QUOTE_PAIRS = (
    ('"', '"'),
    ("'", "'"),
    ("\u00ab", "\u00bb"),
    ("\u2018", "\u2019"),
    ("\u201c", "\u201d"),
    ("\u201e", "\u201f"),
    ("\u2039", "\u203a"),
)


class _StrSubclass(str):
    pass


class _ContainsEverything(str):
    def __contains__(self, item: object) -> bool:
        return True


@pytest.mark.parametrize("product_version", ["0.94", "1.2.3"])
@pytest.mark.parametrize("template", _REFERENCE_TEMPLATES)
def test_product_reference_check_accepts_current_identity_in_every_form(
    template: str,
    product_version: str,
) -> None:
    validate_no_noncurrent_manual_product_references(
        template.format(product_version),
        product_version=product_version,
    )


@pytest.mark.parametrize("visible_version", ["0.93", "0.95", "1.0.0"])
@pytest.mark.parametrize("template", _REFERENCE_TEMPLATES)
def test_product_reference_check_rejects_other_identity_in_every_form(
    template: str,
    visible_version: str,
) -> None:
    with pytest.raises(AssertionError, match="non-current Sector versions"):
        validate_no_noncurrent_manual_product_references(
            template.format(visible_version),
            product_version="0.94",
        )


@pytest.mark.parametrize("space", _HORIZONTAL_SPACES)
@pytest.mark.parametrize("visible_version", ["0.94", "0.93"])
def test_product_reference_check_supports_each_horizontal_space(
    space: str,
    visible_version: str,
) -> None:
    text = (
        f"Sector{space}user{space}manual{space}version{space}"
        f"{visible_version}"
    )
    if visible_version == "0.94":
        validate_no_noncurrent_manual_product_references(
            text,
            product_version="0.94",
        )
    else:
        with pytest.raises(
            AssertionError,
            match="non-current Sector versions",
        ):
            validate_no_noncurrent_manual_product_references(
                text,
                product_version="0.94",
            )


@pytest.mark.parametrize(("opening", "closing"), _QUOTE_PAIRS)
@pytest.mark.parametrize("visible_version", ["0.94", "0.93"])
def test_product_reference_check_supports_each_declared_quote_pair(
    opening: str,
    closing: str,
    visible_version: str,
) -> None:
    text = (
        f"{opening}Sector user manual version{closing}: "
        f"{opening}{visible_version}{closing}"
    )
    if visible_version == "0.94":
        validate_no_noncurrent_manual_product_references(
            text,
            product_version="0.94",
        )
    else:
        with pytest.raises(
            AssertionError,
            match="non-current Sector versions",
        ):
            validate_no_noncurrent_manual_product_references(
                text,
                product_version="0.94",
            )


@pytest.mark.parametrize("separator", ["=", "#"])
@pytest.mark.parametrize(
    "template",
    [
        "Sector version {separator} v{version}",
        "Sector user manual {separator} {version}",
        "Version {separator} {version}",
    ],
)
@pytest.mark.parametrize("visible_version", ["0.94", "0.93", "0.95"])
def test_product_reference_check_supports_declared_equals_and_hash_separators(
    separator: str,
    template: str,
    visible_version: str,
) -> None:
    text = template.format(
        separator=separator,
        version=visible_version,
    )
    if visible_version == "0.94":
        validate_no_noncurrent_manual_product_references(
            text,
            product_version="0.94",
        )
    else:
        with pytest.raises(
            AssertionError,
            match="non-current Sector versions",
        ):
            validate_no_noncurrent_manual_product_references(
                text,
                product_version="0.94",
            )


@pytest.mark.parametrize("separator", ["=", "#"])
def test_product_reference_check_rejects_qualified_separator_identity(
    separator: str,
) -> None:
    with pytest.raises(AssertionError, match="non-current Sector versions"):
        validate_no_noncurrent_manual_product_references(
            f"Sector user manual {separator} 0.94-beta",
            product_version="0.94",
        )


@pytest.mark.parametrize(
    "current_reference",
    [
        "Sector v0.94.",
        '"Sector version 0.94"',
        "(Sector release 0.94)",
        "SECTOR V0.94;",
        "v0.94\u2026",
        "Version 0.94\u3002",
        "\u201cVersion 0.94\u201d",
    ],
)
def test_product_reference_check_accepts_current_punctuation_and_case(
    current_reference: str,
) -> None:
    validate_no_noncurrent_manual_product_references(
        current_reference,
        product_version="0.94",
    )


@pytest.mark.parametrize(
    "qualified_reference",
    [
        "Sector v0.94beta",
        "Sector v0.94-beta",
        "Sector v0.94+build",
        "Sector v0.94_legacy",
        "Sector v0.94/legacy",
        "Sector v0.94\u03b2",
        "Sector v\u0660.\u0669\u0664",
        "Sector user manual version 0.94-beta",
        '"Sector user manual": "v0.94+build"',
        "v0.94-beta",
        "Version 0.94-beta",
        '"Version": "v0.94-beta"',
    ],
)
def test_product_reference_check_rejects_qualified_current_identity(
    qualified_reference: str,
) -> None:
    with pytest.raises(AssertionError, match="non-current Sector versions"):
        validate_no_noncurrent_manual_product_references(
            qualified_reference,
            product_version="0.94",
        )


@pytest.mark.parametrize(
    "unowned_text",
    [
        "",
        "Schema 24",
        "Schema version 25",
        "Previous schema behaviour is documented elsewhere.",
        "Legacy square-root branch",
        "The plane-section assumption no longer holds.",
        "datasector-v0.93",
        "x_sector-v0.93",
        "canvasv0.93",
        "x_v0.93",
        "Python Version 3.13",
        "ReportLab Version 4.4",
        "Python v3.13",
        "ReportLab v4.4",
        "package.v1.2",
        "caf\u00e9V0.93",
        "\u03b2v0.93",
        "\u6e2c\u8a66v0.93",
        "circular sector 2.0 radians",
        "finite sector 3.5 geometry",
        "Current version\n0.93",
        "Version\n0.93",
        "Version\v0.93",
        "Version\f0.93",
        "Version\x850.93",
        "Version\u20280.93",
        "Version\u20290.93",
    ],
)
def test_product_reference_check_ignores_unowned_text(unowned_text: str) -> None:
    validate_no_noncurrent_manual_product_references(
        unowned_text,
        product_version="0.94",
    )


@pytest.mark.parametrize(
    "line_break",
    ["\n", "\r", "\v", "\f", "\x85", "\u2028", "\u2029"],
)
def test_version_label_is_recognised_at_each_real_line_boundary(
    line_break: str,
) -> None:
    with pytest.raises(AssertionError, match="non-current Sector versions"):
        validate_no_noncurrent_manual_product_references(
            "Document control" + line_break + "Version 0.93",
            product_version="0.94",
        )


@pytest.mark.parametrize(
    "line_break",
    ["\n", "\r", "\v", "\f", "\x85", "\u2028", "\u2029"],
)
def test_bare_version_label_is_recognised_at_each_real_line_boundary(
    line_break: str,
) -> None:
    with pytest.raises(AssertionError, match="non-current Sector versions"):
        validate_no_noncurrent_manual_product_references(
            "Document control" + line_break + "v0.93",
            product_version="0.94",
        )


@pytest.mark.parametrize(
    "flat_text",
    [None, 94, b"manual", [], {}, _ContainsEverything("")],
)
def test_product_reference_check_rejects_nontext_content(
    flat_text: object,
) -> None:
    with pytest.raises(AssertionError, match="must be text"):
        validate_no_noncurrent_manual_product_references(
            flat_text,
            product_version="0.94",
        )


@pytest.mark.parametrize(
    "product_version",
    [
        None,
        True,
        False,
        0.94,
        "",
        "0",
        ".94",
        "0.94.",
        "v0.94",
        "0.94-beta",
        "\u0660.\u0669\u0664",
        _StrSubclass("0.94"),
    ],
)
def test_product_reference_check_rejects_malformed_current_version(
    product_version: object,
) -> None:
    with pytest.raises(AssertionError, match="ASCII dotted number"):
        validate_no_noncurrent_manual_product_references(
            "Sector v0.94",
            product_version=product_version,  # type: ignore[arg-type]
        )


def test_product_reference_check_reports_each_distinct_other_identity() -> None:
    with pytest.raises(AssertionError) as exc_info:
        validate_no_noncurrent_manual_product_references(
            "Sector v0.93\nVersion: 0.95\nSector release 0.93",
            product_version="0.94",
        )
    assert str(exc_info.value) == (
        "the manual contains non-current Sector versions: 0.93, 0.95"
    )


def test_product_reference_check_has_required_signature() -> None:
    signature = inspect.signature(
        validate_no_noncurrent_manual_product_references
    )
    parameters = tuple(signature.parameters.values())
    assert tuple(parameter.name for parameter in parameters) == (
        "flat_text",
        "product_version",
    )
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[0].default is inspect.Parameter.empty
    assert parameters[1].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[1].default is inspect.Parameter.empty
    assert get_type_hints(
        validate_no_noncurrent_manual_product_references
    ) == {
        "flat_text": object,
        "product_version": str,
        "return": type(None),
    }


def test_product_reference_module_stays_within_product_identity_scope() -> None:
    source = inspect.getsource(product_references).lower()
    for excluded_term in (
        "schema",
        "legacy",
        "previous",
        "authorit",
        "acceptance",
        "conform",
        "certif",
        "approv",
        "compliance",
        "global pass",
        "global fail",
        "verdict",
    ):
        assert excluded_term not in source
