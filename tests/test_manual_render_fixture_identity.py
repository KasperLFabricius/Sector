"""Browser-free identity checks for the issued manual fixture."""

import pytest

from tools.manual_render_fixture import _validate_release_compatibility_wording


def test_manual_fixture_requires_only_the_current_release_compatibility_wording():
    current = "Current projects use schema version 25"
    migration = (
        "Schema 24 is migrated in memory through the bounded permitted-crack-width "
        "rule and resaves cleanly as schema 25"
    )
    obsolete = "in-development Sector v0.93 line"
    complete = f"{current} {migration}"

    _validate_release_compatibility_wording(complete)

    with pytest.raises(AssertionError, match="expected manual content is missing"):
        _validate_release_compatibility_wording(migration)
    with pytest.raises(AssertionError, match="expected manual content is missing"):
        _validate_release_compatibility_wording(current)
    with pytest.raises(AssertionError, match="obsolete v0.93 development wording"):
        _validate_release_compatibility_wording(f"{complete} {obsolete}")
