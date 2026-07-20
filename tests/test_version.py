"""Release-version contract."""

from sector import __version__


def test_release_version_is_0_80():
    assert __version__ == "0.80"
