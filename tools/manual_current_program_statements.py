"""Dormant current-program statements for the issued user manual."""

CURRENT_REPORT_METADATA_WORDING = (
    "Report details and publication controls are grouped separately from the "
    "Project input stage."
)
CURRENT_RESULT_LABEL_WORDING = (
    "Report labels identify the physical quantity represented by each result field."
)

REPLACED_REPORT_METADATA_WORDING = (
    "Report details and publication controls are no longer mixed with the "
    "Project input stage."
)
REPLACED_RESULT_FIELD_WORDING = "Legacy result-field names remain for compatibility"

_REPLACED_PROGRAM_WORDING = (
    REPLACED_REPORT_METADATA_WORDING,
    REPLACED_RESULT_FIELD_WORDING,
)


def validate_current_manual_program_statements(flat_text: object) -> None:
    """Require the two current program-description statements owned here."""

    if type(flat_text) is not str:
        raise AssertionError("manual current program statements must be text")

    for statement in (
        CURRENT_REPORT_METADATA_WORDING,
        CURRENT_RESULT_LABEL_WORDING,
    ):
        if flat_text.count(statement) != 1:
            raise AssertionError(
                "expected current manual statement must appear exactly once: "
                + statement
            )

    for statement in _REPLACED_PROGRAM_WORDING:
        if statement in flat_text:
            raise AssertionError(
                "the manual still contains a replaced program statement"
            )
