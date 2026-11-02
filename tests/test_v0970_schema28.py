"""Schema 28 migration: earlier projects load with the corrected 0.97.0 methods."""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "app"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import project_io  # noqa: E402

from app import reproducible_example  # noqa: E402
from sector import capacity  # noqa: E402

NEW_KEYS = ("conc_pivot_c", capacity.MED_MAX_ON_KEY, *capacity.MED_MAX_KEYS.values())


def _schema27_text() -> str:
    tables = reproducible_example.project_tables()
    scalars = reproducible_example.project_scalars()
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["version"] = project_io.PREVIOUS_VERSION
    for key in NEW_KEYS:
        payload["scalars"].pop(key, None)
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    return json.dumps(payload)


def test_current_schema_is_28():
    assert project_io.VERSION == 28
    assert 27 in project_io.MIGRATABLE_VERSIONS


def test_schema27_project_loads_with_corrected_methods_and_message():
    _tables, scalars, info = project_io.parse_project_with_info(_schema27_text())
    assert info["source_schema_version"] == 27
    assert info["migrated"] is True
    # The reference project uses the DK NA preset, so pivot C is on.
    assert scalars["conc_pivot_c"] is True
    assert scalars[capacity.MED_MAX_ON_KEY] is False
    assert info["migration_warnings"] == ()
    message = " ".join(info["method_changes"])
    assert "corrected methods" in message
    assert "pivot C" in message
    assert "MEd,max" in message
    assert "NVd/2" in message
    assert "a_l = d" in message
    assert "decompression strain" in message
    assert "Es/Ecm" in message
    assert "upper bound" in message
    assert "max(VRd,c, VRd)" in message


def test_schema28_round_trip_keeps_method_inputs():
    tables = reproducible_example.project_tables()
    scalars = dict(reproducible_example.project_scalars())
    scalars["conc_pivot_c"] = False
    scalars[capacity.MED_MAX_ON_KEY] = True
    scalars["shear_med_max_mx_pos"] = 125.0
    text = project_io.dump_project(tables, scalars)
    _tables, loaded, info = project_io.parse_project_with_info(text)
    assert info["migration_warnings"] == ()
    assert info["method_changes"] == ()
    assert loaded["conc_pivot_c"] is False
    assert loaded[capacity.MED_MAX_ON_KEY] is True
    assert loaded["shear_med_max_mx_pos"] == 125.0
