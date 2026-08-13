"""Immutable presentation policies for Sector calculation reports.

Profiles select publication depth only.  They do not select figures, alter the
result model, recalculate values, or change rounding, statuses, warnings, and
sources.  The legacy ``qa_appendix`` input is accepted only by
:func:`resolve_profile` so existing callers can migrate without making the
compatibility flag part of the profile identity.

The module is deliberately standard-library-only so it is safe to import from
the eager application shell and from lazy report-generation boundaries.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, TypeAlias, cast

ReportProfileKey: TypeAlias = Literal["Brief", "Standard", "Audit"]
InputScope: TypeAlias = Literal["compact", "used", "canonical"]
NonGoverningScope: TypeAlias = Literal["compact", "complete"]
EquationScope: TypeAlias = Literal["interpretive", "used", "used-and-theory"]
SubstitutionScope: TypeAlias = Literal["governing", "material", "every-retained"]
ProvenanceScope: TypeAlias = Literal["revision", "key", "complete"]
GlossaryScope: TypeAlias = Literal["short", "used", "complete"]


@dataclass(frozen=True, slots=True)
class ReportProfilePolicy:
    """One hashable, presentation-only report-depth policy."""

    key: ReportProfileKey
    label: ReportProfileKey
    description: str
    omitted_detail: str
    input_scope: InputScope
    non_governing_scope: NonGoverningScope
    equation_scope: EquationScope
    substitution_scope: SubstitutionScope
    provenance_scope: ProvenanceScope
    glossary_scope: GlossaryScope
    include_qa_appendix: bool
    hard_page_limit: int | None = None
    target_page_limit: int | None = None
    target_exception_requires_reason: bool = False
    target_exception_requires_visual_approval: bool = False
    sparse_page_body_coverage_threshold: float | None = None


BRIEF_PROFILE: Final = ReportProfilePolicy(
    key="Brief",
    label="Brief",
    description=(
        "Rapid-review report with a compact active-input inventory, every "
        "requested calculation result and the governing result chain. "
        "Non-governing results are compact."
    ),
    omitted_detail=(
        "Complete non-governing derivations, full method theory, branch "
        "inventories, hashes, and exhaustive provenance are omitted."
    ),
    input_scope="compact",
    non_governing_scope="compact",
    equation_scope="interpretive",
    substitution_scope="governing",
    provenance_scope="revision",
    glossary_scope="short",
    include_qa_appendix=False,
    target_page_limit=4,
    target_exception_requires_reason=True,
    target_exception_requires_visual_approval=True,
)

STANDARD_PROFILE: Final = ReportProfilePolicy(
    key="Standard",
    label="Standard",
    description=(
        "Default ordinary-design-review report with complete used inputs, "
        "result tables, live methods, material calculation steps, and key "
        "provenance."
    ),
    omitted_detail=(
        "Unused canonical inputs, exhaustive retained branch evidence, hashes, "
        "inventories, and full theory context are omitted."
    ),
    input_scope="used",
    non_governing_scope="complete",
    equation_scope="used",
    substitution_scope="material",
    provenance_scope="key",
    glossary_scope="used",
    include_qa_appendix=False,
    target_page_limit=30,
    target_exception_requires_reason=True,
    target_exception_requires_visual_approval=True,
)

AUDIT_PROFILE: Final = ReportProfilePolicy(
    key="Audit",
    label="Audit",
    description=(
        "Expanded evidence report with canonical inputs, every retained live "
        "step and branch, complete provenance, hashes, and inventories. Audit "
        "does not mean approved, compliant or certified."
    ),
    omitted_detail=(
        "No retained live calculation or provenance detail is intentionally "
        "omitted."
    ),
    input_scope="canonical",
    non_governing_scope="complete",
    equation_scope="used-and-theory",
    substitution_scope="every-retained",
    provenance_scope="complete",
    glossary_scope="complete",
    include_qa_appendix=True,
    sparse_page_body_coverage_threshold=0.35,
)

REPORT_PROFILES: Final[Mapping[ReportProfileKey, ReportProfilePolicy]] = (
    MappingProxyType(
        {
            BRIEF_PROFILE.key: BRIEF_PROFILE,
            STANDARD_PROFILE.key: STANDARD_PROFILE,
            AUDIT_PROFILE.key: AUDIT_PROFILE,
        }
    )
)
REPORT_PROFILE_KEYS: Final[tuple[ReportProfileKey, ...]] = (
    "Brief",
    "Standard",
    "Audit",
)
DEFAULT_PROFILE: Final = STANDARD_PROFILE


def resolve_profile(
    value: str | None = None,
    qa_appendix: bool | None = None,
) -> ReportProfilePolicy:
    """Resolve an exact profile label and optional legacy QA-appendix flag.

    ``None`` selects Standard.  For compatibility, ``qa_appendix=False`` maps
    to Standard and ``qa_appendix=True`` maps to Audit.  When both inputs are
    supplied they must identify the same policy; conflicting, unknown, or
    incorrectly typed inputs fail closed instead of silently changing report
    depth.
    """
    explicit: ReportProfilePolicy | None = None
    if value is not None:
        if not isinstance(value, str):
            raise TypeError("report profile must be a string or None")
        if value not in REPORT_PROFILES:
            expected = ", ".join(REPORT_PROFILE_KEYS)
            raise ValueError(
                f"unknown report profile {value!r}; expected one of: {expected}"
            )
        explicit = REPORT_PROFILES[cast(ReportProfileKey, value)]

    legacy: ReportProfilePolicy | None = None
    if qa_appendix is not None:
        if type(qa_appendix) is not bool:
            raise TypeError("qa_appendix must be a bool or None")
        legacy = AUDIT_PROFILE if qa_appendix else STANDARD_PROFILE

    if explicit is not None and legacy is not None and explicit is not legacy:
        raise ValueError(
            "report profile conflicts with the legacy qa_appendix selection"
        )
    return explicit or legacy or DEFAULT_PROFILE
