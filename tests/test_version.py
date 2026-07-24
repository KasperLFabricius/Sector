"""Release-version contract."""

from sector import __author__, __licensee__, __version__


def test_release_version_is_0_91():
    assert __version__ == "0.91"
    assert __author__ == "Kasper Lindskov Fabricius"
    assert __licensee__ == "Sweco Danmark A/S"
