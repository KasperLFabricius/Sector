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
from sector import capacity, codes  # noqa: E402

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


def test_schema27_project_with_the_2023_preset_loads_without_pivot_c():
    # DS/EN 1992-1-1:2023 8.1.1(3) limits only eps_cu, so the migrated default
    # of the pivot C limit is off for the 2023 concrete preset.
    payload = json.loads(_schema27_text())
    payload["scalars"]["conc_preset"] = codes.EC2_2023.label
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    _tables, scalars, info = project_io.parse_project_with_info(json.dumps(payload))
    assert info["source_schema_version"] == 27
    assert scalars["conc_preset"] == codes.EC2_2023.label
    assert scalars["conc_pivot_c"] is False
    assert scalars[capacity.MED_MAX_ON_KEY] is False
    assert all(scalars[key] == 0.0 for key in capacity.MED_MAX_KEYS.values())


def test_load_message_uses_one_edition_name():
    message = " ".join(project_io.SCHEMA28_METHOD_CHANGES)
    assert "2005 family" not in message
    assert "EN 1992-1-1:2004" in message
    assert "6.1(6) and Figure 6.1" in message


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
