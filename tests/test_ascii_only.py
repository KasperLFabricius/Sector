"""Guard: the source tree must stay strictly ASCII.

Non-ASCII characters (in source, or echoed through tooling output) have caused
session-breaking encoding errors, so the repository is kept ASCII-only. This
test fails if any tracked source or documentation file contains a byte above
0x7F, reporting only byte offsets -- never the offending character -- so the
failure message itself stays ASCII.
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _source_files():
    seen = set()
    for pattern in ("sector/**/*.py", "tests/**/*.py", "*.py", "*.md"):
        for path in ROOT.glob(pattern):
            # Skip scratch files (a single leading underscore, e.g. _audit.py)
            # but keep dunder source files such as __init__.py.
            is_scratch = path.name.startswith("_") and not path.name.startswith("__")
            if is_scratch or path in seen:
                continue
            seen.add(path)
            yield path


@pytest.mark.parametrize("path", sorted(_source_files()), ids=lambda p: p.name)
def test_file_is_ascii(path):
    data = path.read_bytes()
    offsets = [i for i, b in enumerate(data) if b > 0x7F]
    assert not offsets, (
        f"{path.name}: non-ASCII byte(s) at offset(s) {offsets[:8]} "
        f"({len(offsets)} total) -- replace with ASCII equivalents"
    )
