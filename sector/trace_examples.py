"""Load the sealed PI-019 reference calculations used by the issued manual."""

from __future__ import annotations

import base64
import functools
import gzip
import json
from pathlib import Path

from sector.calculation_trace import TraceBundle, validate_bundle


_REFERENCE_FILE = Path(__file__).with_name("manual_trace_examples.b64")
_EXPECTED_COVERAGE = frozenset(f"CT-{index:03d}" for index in range(1, 28))


@functools.lru_cache(maxsize=1)
def reference_bundle() -> TraceBundle:
    """Return the validated, solver-emitted manual reference bundle.

    The compact text resource is packaged beside this module.  Validation on
    load prevents the manual from publishing a stale, reordered or edited
    derivation as if it were sealed solver output.
    """

    encoded = _REFERENCE_FILE.read_text(encoding="ascii")
    payload = json.loads(gzip.decompress(base64.b64decode(encoded)).decode("utf-8"))
    bundle = validate_bundle(payload)
    coverage = frozenset(
        calculation.coverage_id for calculation in bundle.calculations
    )
    if coverage != _EXPECTED_COVERAGE:
        missing = sorted(_EXPECTED_COVERAGE - coverage)
        unexpected = sorted(coverage - _EXPECTED_COVERAGE)
        raise ValueError(
            "Manual trace coverage mismatch "
            f"(missing={missing}, unexpected={unexpected})."
        )
    return bundle
