"""Dormant current schema and product identity contract for the user manual."""

from __future__ import annotations

import re


CURRENT_PROJECT_SAVE_WORDING = (
    "Every downloaded project save uses the current schema"
)

_PRODUCT_VERSION_FORMAT = re.compile(r"[0-9]+(?:\.[0-9]+)+")
_REFERENCE_SUFFIX = r"[^\s,;:!?()\[\]{}\"'<>]*"
_REFERENCE_TOKEN = rf"(?P<version>\d{_REFERENCE_SUFFIX})"
_DOTTED_REFERENCE_TOKEN = (
    rf"(?P<version>\d{_REFERENCE_SUFFIX}\.\d{_REFERENCE_SUFFIX})"
)
_SCHEMA_REFERENCE = re.compile(
    r"\bschema(?:\s+version)?\s*:?\s*v?\s*"
    + _REFERENCE_TOKEN,
    flags=re.IGNORECASE,
)
_SECTOR_VERSION_REFERENCE = re.compile(
    r"\bSector(?:\s+user\s+manual)?\s+"
    r"(?:(?:version|release)\s*:?\s*)?v?\s*"
    + _REFERENCE_TOKEN,
    flags=re.IGNORECASE,
)
_BARE_PRODUCT_VERSION_REFERENCE = re.compile(
    r"\bv\s*" + _DOTTED_REFERENCE_TOKEN,
    flags=re.IGNORECASE,
)


def current_schema_wording(project_schema: int) -> str:
    """Return the exact issued-manual statement for one current schema."""

    if type(project_schema) is not int or project_schema <= 0:
        raise AssertionError("current project schema must be a positive integer")
    return f"Current projects use schema version {project_schema}"


def validate_current_manual_identity(
    flat_text: object,
    *,
    project_schema: int,
    product_version: str,
) -> None:
    """Require current identity and reject every other visible schema/version."""

    if not isinstance(flat_text, str):
        raise AssertionError("manual current identity must be text")
    schema_wording = current_schema_wording(project_schema)
    if not isinstance(product_version, str) or not _PRODUCT_VERSION_FORMAT.fullmatch(
        product_version
    ):
        raise AssertionError(
            "current product version must be an ASCII dotted number"
        )
    if schema_wording not in flat_text:
        raise AssertionError(
            "expected manual content is missing: " + schema_wording
        )
    if CURRENT_PROJECT_SAVE_WORDING not in flat_text:
        raise AssertionError(
            "expected manual content is missing: "
            + CURRENT_PROJECT_SAVE_WORDING
        )

    schema_versions = {
        match.group("version").rstrip(".")
        for match in _SCHEMA_REFERENCE.finditer(flat_text)
    }
    historical_schemas = sorted(
        version
        for version in schema_versions
        if version != str(project_schema)
    )
    if historical_schemas:
        raise AssertionError(
            "the manual contains non-current schema references: "
            + ", ".join(historical_schemas)
        )

    product_versions = {
        match.group("version").rstrip(".")
        for pattern in (
            _SECTOR_VERSION_REFERENCE,
            _BARE_PRODUCT_VERSION_REFERENCE,
        )
        for match in pattern.finditer(flat_text)
    }
    historical_products = sorted(
        version for version in product_versions if version != product_version
    )
    if historical_products:
        raise AssertionError(
            "the manual contains non-current Sector version references: "
            + ", ".join(historical_products)
        )
    if product_version not in product_versions:
        raise AssertionError(
            "expected current Sector product version is missing: "
            + product_version
        )
