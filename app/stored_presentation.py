"""Stored result presentation: one build for each Calculate (AR-01, UI-01).

The result register (the summary rows of all action sets) takes seconds to
build, because its publication validators calculate retained values again.
Sector therefore builds it one time after each successful Calculate and keeps
it in the session beside the solver results, in the key ``SESSION_KEY``. A
page change or a rerun then reads the stored rows. The stored presentation is
not part of the solver results, ``project_io.result_sha256`` or the project
file.

Record (``SCHEMA`` 1)::

    {
        "schema": 1,
        "engineering_input_sha256": str,  # sha of inp["signature"], the same
                                          # value as the calculation record
        "input_scalars_sha256": str,      # the plain scalar entries of inp
        "result_sha256": str,             # project_io.result_sha256(results)
        "source_revision": str,           # sector.build_info.source_revision()
        "capacity_contract": [str, ...],  # capacity result contract token
        "stale": bool,                    # False: built at Calculate
        "sections": {
            "S1": {                       # SECTION_KEY, one section for now
                "stages": {
                    "final": {            # STAGE_KEY, the only stage for now
                        "rows": [row, ...],       # register order
                        "rows_sha256": str,       # result_sha256(rows)
                        "cases": {                # case key -> row positions
                            "plastic:PL-1": [0, 1, 2],
                            "elastic:EL-1": [7, 8],
                        },
                        "governing": [0, 7],      # governing row of each
                                                  # check type, in order
                    },
                },
            },
        },
        "variants": {key: record without "variants"},  # at most MAX_VARIANTS
    }

A row is a ``result_presentation.multi_case_summary_rows`` row. A case key is
``"<family>:<case>"``, from the ``family`` and ``case`` fields of the row
(``case`` is ``"-"`` for a result of the section, for example clear spacing).
``case_rows`` and ``governing_rows`` read one stage.

Digest contract. Stored rows are read only when the engineering input
SHA-256, the scalar inputs SHA-256, the result SHA-256 and the source revision
of the request agree with the record, and the rows agree with their digest.
Any mismatch or a malformed record gives no stored rows, and the caller
calculates the rows again (fail closed). The capacity contract token is part
of the engineering signature, so a changed contract also changes the
engineering input SHA-256. A presentation that the application calculates
again for the same calculation, for example the stale form after an input edit,
is kept as a variant, so it is calculated at most one time for each digest
set.

``activate`` makes a record the source for the current script run.
``result_presentation.multi_case_summary_rows`` reads the active record.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
import copy
import sys

if __name__ in {"app.stored_presentation", "stored_presentation"}:
    # The flat layout lets the module load under two names. One module object
    # keeps one active record.
    _THIS_MODULE = sys.modules[__name__]
    for _module_name in ("app.stored_presentation", "stored_presentation"):
        sys.modules.setdefault(_module_name, _THIS_MODULE)

SCHEMA = 1
SESSION_KEY = "result_presentation"
SECTION_KEY = "S1"
STAGE_KEY = "final"
MAX_VARIANTS = 4
_SCALAR_TYPES = (str, int, float, bool, type(None))
_ACTIVE = ContextVar("stored_result_presentation", default=None)


def _project_io():
    import project_io

    return project_io


def source_revision() -> str:
    from sector.build_info import source_revision as revision

    return revision()


def engineering_input_sha256(inp) -> str | None:
    """Return the engineering input SHA-256 of ``inp``, or None without a signature.

    The value is the same as ``engineering_input_sha256`` of the calculation
    record (``_engineering_input_hash`` in ``sector_app``).
    """

    if not isinstance(inp, Mapping) or inp.get("signature") is None:
        return None
    try:
        return _project_io().result_sha256(
            ("sector-engineering-input-v1", inp["signature"])
        )
    except (TypeError, ValueError):
        return None


def input_scalars_sha256(inp) -> str | None:
    """Return the SHA-256 of the plain scalar entries of ``inp``.

    The engineering signature covers the engineering inputs. The scalar
    entries add each option of ``inp`` that the signature does not hold, so
    a stored presentation is never read for other inputs.
    """

    if not isinstance(inp, Mapping):
        return None
    scalars = {
        str(key): value
        for key, value in inp.items()
        if type(value) in _SCALAR_TYPES
    }
    try:
        return _project_io().result_sha256(("sector-input-scalars-v1", scalars))
    except (TypeError, ValueError):
        return None


def _result_sha256(results) -> str | None:
    try:
        return _project_io().result_sha256(results if results is not None else {})
    except (TypeError, ValueError):
        return None


def case_key(row) -> str:
    return f"{row.get('family') or '-'}:{row.get('case') or '-'}"


def _stage(rows, governing) -> dict:
    cases: dict[str, list[int]] = {}
    for position, row in enumerate(rows):
        cases.setdefault(case_key(row), []).append(position)
    return {
        "rows": rows,
        "rows_sha256": _project_io().result_sha256(rows),
        "cases": cases,
        "governing": [int(position) for position in governing],
    }


def new_record(
    inp,
    results,
    rows,
    *,
    governing=(),
    stale=False,
    revision=None,
    capacity_contract=(),
) -> dict | None:
    """Return a record for ``rows`` of ``inp`` and ``results``, or None.

    None means that the inputs have no engineering signature or that a digest
    cannot be calculated; the caller then keeps no stored presentation.
    """

    digests = (
        engineering_input_sha256(inp),
        input_scalars_sha256(inp),
        _result_sha256(results),
    )
    if any(value is None for value in digests):
        return None
    rows = copy.deepcopy(list(rows))
    try:
        stage = _stage(rows, governing)
    except (TypeError, ValueError):
        return None
    return {
        "schema": SCHEMA,
        "engineering_input_sha256": digests[0],
        "input_scalars_sha256": digests[1],
        "result_sha256": digests[2],
        "source_revision": str(
            source_revision() if revision is None else revision
        ),
        "capacity_contract": [str(item) for item in capacity_contract],
        "stale": bool(stale),
        "sections": {SECTION_KEY: {"stages": {STAGE_KEY: stage}}},
        "variants": {},
    }


def stage(record, section=SECTION_KEY, stage_key=STAGE_KEY):
    """Return one stage of a record, or None when the record has no such stage."""

    try:
        value = record["sections"][section]["stages"][stage_key]
    except (KeyError, TypeError):
        return None
    return value if isinstance(value, Mapping) else None


def case_rows(record, key, section=SECTION_KEY, stage_key=STAGE_KEY) -> list:
    """Return copies of the stored rows of one case key (``"<family>:<case>"``)."""

    found = stage(record, section, stage_key)
    if found is None:
        return []
    rows = found.get("rows") or []
    return [
        copy.deepcopy(rows[position])
        for position in found.get("cases", {}).get(key, ())
        if 0 <= position < len(rows)
    ]


def governing_rows(record, section=SECTION_KEY, stage_key=STAGE_KEY) -> list:
    """Return copies of the stored governing rows, one for each check type."""

    found = stage(record, section, stage_key)
    if found is None:
        return []
    rows = found.get("rows") or []
    return [
        copy.deepcopy(rows[position])
        for position in found.get("governing", ())
        if 0 <= position < len(rows)
    ]


def _variant_key(scalars_sha256, stale) -> str:
    return f"{scalars_sha256}:{'stale' if stale else 'current'}"


def _base_matches(record, inp, results) -> bool:
    if not isinstance(record, Mapping) or record.get("schema") != SCHEMA:
        return False
    if record.get("source_revision") != source_revision():
        return False
    engineering = engineering_input_sha256(inp)
    if engineering is None or engineering != record.get("engineering_input_sha256"):
        return False
    return _result_sha256(results) == record.get("result_sha256")


def _verified_rows(presentation):
    found = stage(presentation)
    if found is None:
        return None
    rows = found.get("rows")
    if not isinstance(rows, list):
        return None
    try:
        if _project_io().result_sha256(rows) != found.get("rows_sha256"):
            return None
    except (TypeError, ValueError):
        return None
    return copy.deepcopy(rows)


def read_rows(record, inp, results, *, stale=False):
    """Return copies of the stored rows for this request, or None (fail closed)."""

    if not _base_matches(record, inp, results):
        return None
    scalars = input_scalars_sha256(inp)
    if scalars is None:
        return None
    if (
        record.get("input_scalars_sha256") == scalars
        and bool(record.get("stale")) is bool(stale)
    ):
        return _verified_rows(record)
    variants = record.get("variants")
    if not isinstance(variants, Mapping):
        return None
    variant = variants.get(_variant_key(scalars, stale))
    if not isinstance(variant, Mapping):
        return None
    return _verified_rows(variant)


def remember_variant(record, inp, results, rows, *, stale=False, governing=()):
    """Keep a presentation calculated again for the calculation of ``record``.

    Nothing is kept when the engineering inputs, the results or the source
    revision differ from the record: the rows then belong to another
    calculation. The oldest variant goes when the record has ``MAX_VARIANTS``.
    """

    if not isinstance(record, dict) or not _base_matches(record, inp, results):
        return False
    variant = new_record(
        inp,
        results,
        rows,
        governing=governing,
        stale=stale,
        revision=record.get("source_revision"),
        capacity_contract=record.get("capacity_contract") or (),
    )
    if variant is None:
        return False
    variant.pop("variants", None)
    variants = record.setdefault("variants", {})
    if not isinstance(variants, dict):
        return False
    key = _variant_key(variant["input_scalars_sha256"], stale)
    variants.pop(key, None)
    while len(variants) >= MAX_VARIANTS:
        variants.pop(next(iter(variants)))
    variants[key] = variant
    return True


def activate(record) -> None:
    """Make ``record`` (or None) the stored presentation of this script run."""

    _ACTIVE.set(record if isinstance(record, Mapping) else None)


def active_record():
    return _ACTIVE.get()
