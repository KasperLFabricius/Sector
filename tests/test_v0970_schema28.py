"""Schema 28 migration: earlier projects load with the corrected 0.97.0 methods."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "app"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import project_io  # noqa: E402

from app import reinforcement_table, reproducible_example  # noqa: E402
from sector import capacity, codes  # noqa: E402

NEW_KEYS = (
    "conc_pivot_c",
    capacity.MED_MAX_ON_KEY,
    *capacity.MED_MAX_KEYS.values(),
    capacity.SHEAR_TENDONS_KEY,
)


def _schema27_text(*, tendons=None, **scalar_changes) -> str:
    tables = reproducible_example.project_tables()
    if tendons is not None:
        tables["tendons_base"] = reinforcement_table.table_from_points(
            tendons, "tendon"
        )
    scalars = dict(reproducible_example.project_scalars(), **scalar_changes)
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
    # The reference project uses 2005 shear: the bonded tendons stay out of Asl
    # and d (EN 1992-2 6.2.2(101) only permits them).
    assert scalars[capacity.SHEAR_TENDONS_KEY] is False
    # The tendon change applies only to 2023 shear, so the message omits it.
    assert "Formulae (8.36) and (8.37)" not in message
    assert "decompression strain" in message
    assert "Es/Ecm" in message
    assert "upper bound" in message
    assert "max(VRd,c, VRd)" in message


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


def test_schema27_project_without_the_preset_gets_pivot_c_of_the_default_preset(
    tmp_path, monkeypatch
):
    # Owner decision 1: pivot C is on by default for the Eurocode presets. The
    # default concrete preset of the app is the 2005 edition with the DK NA.
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    payload = json.loads(_schema27_text())
    del payload["scalars"]["conc_preset"]
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    text = json.dumps(payload)
    _tables, scalars, info = project_io.parse_project_with_info(text)
    assert info["source_schema_version"] == 27
    assert "conc_preset" not in scalars
    assert scalars["conc_pivot_c"] is True

    app = pathlib.Path(__file__).resolve().parents[1] / "app" / "sector_app.py"
    at = AppTest.from_file(str(app), default_timeout=120).run()
    at.session_state["_pending_project"] = text
    at.run()
    assert not at.exception
    assert at.session_state["conc_preset"] == "DS/EN 1992-1-1:2005 + DK NA:2024"
    assert at.session_state["conc_pivot_c"] is True


def test_load_message_states_a_pivot_c_limit_that_the_file_clears():
    # An edited file can clear the limit. The load keeps this explicit value, so
    # the message must not state that the limit applies without this correction.
    cleared = " does not apply it."
    _tables, scalars, info = project_io.parse_project_with_info(_schema27_text())
    assert scalars["conc_pivot_c"] is True
    assert cleared not in " ".join(info["method_changes"])

    payload = json.loads(_schema27_text())
    payload["scalars"]["conc_pivot_c"] = False
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    _tables, scalars, info = project_io.parse_project_with_info(json.dumps(payload))
    assert scalars["conc_pivot_c"] is False
    assert cleared in " ".join(info["method_changes"])


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


def test_schema27_project_with_2023_shear_includes_the_tendons():
    # DS/EN 1992-1-1:2023 8.2.2(6): d and rho_l include Ap, so the migrated
    # default of the tendon option is on when the effective shear method is 2023.
    payload = json.loads(_schema27_text())
    payload["scalars"]["shear_method"] = codes.EC2_2023.label
    payload["scalars"]["combined_on"] = False
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    tables, scalars, info = project_io.parse_project_with_info(json.dumps(payload))
    assert info["source_schema_version"] == 27
    assert scalars[capacity.SHEAR_TENDONS_KEY] is True
    # The reference project has no tendons, so nothing changes and the load
    # message omits the tendon change (the case with tendons is tested below).
    assert len(tables["tendons_base"]) == 0
    assert project_io.SCHEMA28_TENDON_CHANGE not in " ".join(info["method_changes"])


def test_schema27_project_takes_the_shear_method_from_combined():
    # The app takes the shear method from Combined when Combined is on. With
    # 2023 shear and a 2004-family Combined method, the effective method is the
    # 2004 family, so the tendon option stays off.
    payload = json.loads(_schema27_text(tendons=[(0.0, -200.0, 600.0)]))
    payload["scalars"]["shear_method"] = codes.EC2_2023.label
    assert payload["scalars"]["combined_on"] is True
    assert payload["scalars"]["combined_method"] == codes.EC2_2005_DKNA.label
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    _tables, scalars, info = project_io.parse_project_with_info(json.dumps(payload))
    assert scalars[capacity.SHEAR_TENDONS_KEY] is False
    assert project_io.SCHEMA28_TENDON_CHANGE not in " ".join(info["method_changes"])


def test_tendon_load_message_is_conditional():
    base = project_io.schema28_migration_warning()
    with_tendons = project_io.schema28_migration_warning(tendons_2023=True)
    assert project_io.SCHEMA28_TENDON_CHANGE not in base
    assert project_io.SCHEMA28_TENDON_CHANGE in with_tendons
    assert "Formulae (8.36) and (8.37)" in project_io.SCHEMA28_TENDON_CHANGE


def test_schema28_round_trip_keeps_the_tendon_option():
    tables = reproducible_example.project_tables()
    for value in (True, False):
        scalars = dict(reproducible_example.project_scalars())
        scalars[capacity.SHEAR_TENDONS_KEY] = value
        text = project_io.dump_project(tables, scalars)
        assert json.loads(text)["scalars"][capacity.SHEAR_TENDONS_KEY] is value
        _tables, loaded, info = project_io.parse_project_with_info(text)
        assert info["method_changes"] == ()
        assert loaded[capacity.SHEAR_TENDONS_KEY] is value


def test_tendon_option_rejects_a_non_boolean_value():
    import pytest

    tables = reproducible_example.project_tables()
    scalars = dict(reproducible_example.project_scalars())
    scalars[capacity.SHEAR_TENDONS_KEY] = True
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["scalars"][capacity.SHEAR_TENDONS_KEY] = 1
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    with pytest.raises(ValueError):
        project_io.parse_project_with_info(json.dumps(payload))


def test_schema27_2023_project_with_tendons_states_the_tendon_change():
    text = _schema27_text(
        tendons=[(0.0, -200.0, 600.0)],
        shear_method=codes.EC2_2023.label,
        combined_on=False,
    )
    _tables, scalars, info = project_io.parse_project_with_info(text)
    assert scalars[capacity.SHEAR_TENDONS_KEY] is True
    assert project_io.SCHEMA28_TENDON_CHANGE in " ".join(info["method_changes"])
    text = _schema27_text(tendons=[(0.0, -200.0, 600.0)])
    _tables, scalars, info = project_io.parse_project_with_info(text)
    assert scalars[capacity.SHEAR_TENDONS_KEY] is False
    assert project_io.SCHEMA28_TENDON_CHANGE not in " ".join(info["method_changes"])


@pytest.mark.parametrize(
    "changes",
    [
        {"shear_on": False},
        {"shear_duct_case": "Not grouted, soft-filled, or unbonded"},
    ],
)
def test_tendon_change_is_not_stated_when_it_changes_nothing(changes):
    text = _schema27_text(
        tendons=[(0.0, -200.0, 600.0)],
        shear_method=codes.EC2_2023.label,
        combined_on=False,
        **changes,
    )
    _tables, _scalars, info = project_io.parse_project_with_info(text)
    assert project_io.SCHEMA28_TENDON_CHANGE not in " ".join(info["method_changes"])


def _development_schema28_text(app_version, *, tendons=None, **scalar_changes) -> str:
    # A schema-28 file without the tendon option, as development builds wrote
    # it between the schema 28 change and the 0.97.0 release.
    tables = reproducible_example.project_tables()
    if tendons is not None:
        tables["tendons_base"] = reinforcement_table.table_from_points(
            tendons, "tendon"
        )
    scalars = dict(reproducible_example.project_scalars(), **scalar_changes)
    scalars.pop(capacity.SHEAR_TENDONS_KEY)
    return project_io.dump_project(tables, scalars, app_version=app_version)


def test_development_schema28_file_loads_with_the_message():
    # Codex review of PR #578: such a file loaded without a load message, and
    # the tendon option then followed the 2023 default without notice.
    changes = dict(tendons=[(0.0, -200.0, 600.0)],
                   shear_method=codes.EC2_2023.label, combined_on=False)
    text = _development_schema28_text("0.96.9", **changes)
    _tables, scalars, info = project_io.parse_project_with_info(text)
    assert info["source_schema_version"] == project_io.VERSION
    assert scalars[capacity.SHEAR_TENDONS_KEY] is True
    message = " ".join(info["method_changes"])
    assert project_io.SCHEMA28_TENDON_CHANGE in message
    assert "decompression strain" in message
    # A 2005 shear project gets the general message without the tendon change.
    text = _development_schema28_text("0.96.9", tendons=[(0.0, -200.0, 600.0)])
    _tables, scalars, info = project_io.parse_project_with_info(text)
    assert scalars[capacity.SHEAR_TENDONS_KEY] is False
    message = " ".join(info["method_changes"])
    assert message and project_io.SCHEMA28_TENDON_CHANGE not in message


def test_released_schema28_file_loads_without_the_message():
    text = project_io.dump_project(
        reproducible_example.project_tables(),
        reproducible_example.project_scalars(),
        app_version="0.97.0",
    )
    _tables, _scalars, info = project_io.parse_project_with_info(text)
    assert info["method_changes"] == ()
