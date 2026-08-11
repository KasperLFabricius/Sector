"""Browser-free identity checks for the issued manual fixture."""

import pytest

from tools.manual_render_fixture import _validate_release_compatibility_wording


def test_manual_fixture_requires_only_the_current_release_compatibility_wording():
    current = "Sector v0.93 supports only current project schema version 24"
    obsolete = "in-development Sector v0.93 line"

    _validate_release_compatibility_wording(current)

    with pytest.raises(AssertionError, match="expected manual content is missing"):
        _validate_release_compatibility_wording("Released Sector 0.92")
    with pytest.raises(AssertionError, match="obsolete v0.93 development wording"):
        _validate_release_compatibility_wording(f"{current} {obsolete}")
