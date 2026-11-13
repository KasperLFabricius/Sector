"""0.97.1 F2 (AR-07): the calculation service module and its headless entry.

The calculation functions moved from ``app/sector_app.py`` to
``app/calculation_service.py``, unchanged except the cache decorator of
``_warm_solver`` and one comment about the member-angle scan. These tests hold
the module contract: the
re-export from ``sector_app``, no Streamlit import in the service, and the
``calculate_project`` entry and command line. The engineering values are the
existing results; a test here compares two routes of the same calculation and
does not set an expected engineering value.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import pathlib
import pickle
import re
import subprocess
import sys

import pytest
from streamlit.testing.v1 import AppTest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import project_io  # noqa: E402
import reproducible_example  # noqa: E402
import sector_app  # noqa: E402
from app import calculation_service  # noqa: E402
from tools import report_render_fixture  # noqa: E402

SERVICE = ROOT / "app" / "calculation_service.py"
APP = str(ROOT / "app" / "sector_app.py")

# The names that sector_app imports again for one release (0.97.1 to 0.97.2).
MOVED_NAMES = (
    "solve_elastic_combined", "transformed_properties", "solve_interaction",
    "solve_plastic", "analyse_cracking", "combined_cracking", "crack_width",
    "evaluate_crack_width", "_warm_solver", "_SLAB_DENSITY_GUIDANCE",
    "_SLAB_TENDON_FACE_GUIDANCE", "_slab_face_clear_cover_mm",
    "_slab_tendon_face_clear_cover_mm", "_sweep", "_props_dict",
    "_plastic_point_result", "_elastic_resultant_result", "_elastic_state_result",
    "_area_moments_dict", "_section_and_material_results", "_elastic_solver_inputs",
    "_crack_dict", "_outline_bbox", "_shear_lever_arm", "_shear_face_mrd",
    "_tube_torsion", "_run_single_analysis", "_run_fatigue_or_invalid",
    "_HEIGHTENED_POSITIVE_INPUTS", "_HEIGHTENED_BOOLEAN", "_HEIGHTENED_ELASTIC_MODE",
    "_HEIGHTENED_DESIGN_BASIS", "_HEIGHTENED_SURFACE",
    "_HEIGHTENED_POSITIVE_MESSAGES", "_HEIGHTENED_REFERENCE_REQUIRED",
    "_HEIGHTENED_REFERENCE_SELECT", "_HEIGHTENED_REFERENCE_DISPLAY",
    "_heightened_crack_control_validation_errors",
    "_heightened_crack_control_payload", "_attach_heightened_crack_control",
    "_clear_spacing_result", "run_analysis", "_run_uniaxial_capacity_checks",
    "_directional_shear_status", "_shear_candidate_assessment",
    "_minimum_reinf_assessment", "_candidate_domain_cot", "_governing_domain",
    "_torsion_interaction_assessment", "_combined_direction_assessment",
    "_direction_input", "_run_capacity_checks", "_direction_detailing_depth",
    "_transverse_detailing_result", "_formula_631_detailing_state",
    "_attach_formula_631_detailing_state",
)


def _top_level_names(path):
    names = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def test_sector_app_re_exports_each_moved_name_as_the_same_object():
    for name in MOVED_NAMES:
        assert getattr(sector_app, name) is getattr(calculation_service, name), name
    defined_in_app = _top_level_names(ROOT / "app" / "sector_app.py")
    assert defined_in_app.isdisjoint(MOVED_NAMES)
    assert set(MOVED_NAMES) <= _top_level_names(SERVICE)
    assert calculation_service.run_analysis.__module__ == "app.calculation_service"


def test_service_has_no_streamlit_import_at_module_level():
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    module_imports = [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    imported = {
        alias.name for node in module_imports if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in module_imports if isinstance(node, ast.ImportFrom)}
    assert not {name for name in imported if name.split(".")[0] == "streamlit"}


def _run_isolated(script: str) -> str:
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=ROOT, capture_output=True, text=True, timeout=300, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize("app_on_path", [False, True], ids=["root-only", "root-and-app"])
def test_service_imports_with_the_repository_root_alone_and_loads_no_streamlit(
    app_on_path,
):
    # -I gives a sys.path without the current folder; the script then adds only
    # the folders of the case.
    folders = [str(ROOT), str(ROOT / "app")] if app_on_path else [str(ROOT)]
    output = _run_isolated(
        "import sys\n"
        f"sys.path[:0] = {folders!r}\n"
        "from app import calculation_service\n"
        "loaded = [m for m in sys.modules if m.split('.')[0] == 'streamlit']\n"
        f"print(len(loaded), sys.path.count({str(ROOT / 'app')!r}))\n"
    )
    assert output == "0 1"


@pytest.mark.parametrize("first", ["app.calculation_service", "calculation_service"])
def test_both_module_names_give_one_module_object(first):
    second = (
        "calculation_service" if first == "app.calculation_service"
        else "app.calculation_service"
    )
    output = _run_isolated(
        "import importlib, sys\n"
        f"sys.path[:0] = [{str(ROOT)!r}, {str(ROOT / 'app')!r}]\n"
        f"a = importlib.import_module({first!r})\n"
        f"b = importlib.import_module({second!r})\n"
        "import app\n"
        "from app import calculation_service as c\n"
        "print(a is b, b is c, app.calculation_service is a,"
        " a._warm_solver is b._warm_solver)\n"
    )
    assert output == "True True True True"


def test_calculation_in_a_new_process_loads_no_streamlit(tmp_path):
    # Inputs prepared here and pickled; the new process has never run the
    # application, so a Streamlit import during the calculation would show.
    inp = report_render_fixture._inputs()
    expected = project_io.result_sha256(sector_app.run_analysis(copy.deepcopy(inp)))
    prepared = tmp_path / "inputs.pickle"
    prepared.write_bytes(pickle.dumps(inp))
    output = _run_isolated(
        "import pickle, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from app import calculation_service\n"
        "assert not [m for m in sys.modules if m.split('.')[0] == 'streamlit']\n"
        f"inputs = pickle.loads(open({str(prepared)!r}, 'rb').read())\n"
        "result_set = calculation_service.calculate_project(inputs)\n"
        "loaded = [m for m in sys.modules if m.split('.')[0] == 'streamlit']\n"
        "print(len(loaded), result_set['result_sha256'])\n"
    )
    assert output == f"0 {expected}"


def test_calculate_project_matches_run_analysis_for_an_input_document():
    inp = report_render_fixture._inputs()
    expected = project_io.result_sha256(sector_app.run_analysis(copy.deepcopy(inp)))

    single = calculation_service.calculate_project(copy.deepcopy(inp))
    assert set(single) == {"inputs", "results", "result_sha256"}
    assert single["result_sha256"] == project_io.result_sha256(single["results"])
    assert single["result_sha256"] == expected

    several = calculation_service.calculate_project(
        [copy.deepcopy(inp), copy.deepcopy(inp)]
    )
    assert isinstance(several, list)
    assert [item["result_sha256"] for item in several] == [expected, expected]


@pytest.mark.parametrize(
    "item",
    [
        3, (1, 2, 3), b"{}", ("{}", "{}"), ({}, "{}"),
        ({"section": None}, {"section": None}),
    ],
    ids=[
        "number", "three-tuple", "bytes", "two-texts", "mapping-and-text",
        "two-input-documents",
    ],
)
def test_calculate_project_rejects_an_item_that_is_not_a_project(item):
    with pytest.raises(TypeError, match="project must be"):
        calculation_service.calculate_project(item)


def test_invalid_section_gives_an_empty_result_set_and_summary_message():
    inp = report_render_fixture._inputs()
    inp["geometry_error"] = "The outline crosses itself"
    result_set = calculation_service.calculate_project(inp)
    assert result_set["results"] == {}
    assert calculation_service._summary_lines("p.json", result_set, 0.0, 0.0) == [
        "Project: p.json",
        "No results. Correct the section, reinforcement or material inputs.",
    ]


def _changed_reference_project() -> str:
    changed = json.loads(reproducible_example.project_json())
    rows = changed["tables"]["corners_base"]["rows"]
    changed["tables"]["corners_base"]["rows"] = rows[:2]
    return json.dumps(changed)


@pytest.mark.parametrize(
    ("text", "detail"),
    [
        (_changed_reference_project(), "damaged or was changed outside Sector"),
        ("{", "not a readable Sector project"),
    ],
    ids=["changed-file", "not-json"],
)
def test_project_that_sector_does_not_apply_is_not_calculated(text, detail):
    # The application keeps the default session after a rejected file. The
    # service must not calculate those default inputs as if they were the file.
    with pytest.raises(ValueError, match="New file was not applied") as caught:
        calculation_service.calculate_project(text)
    assert detail in str(caught.value)


class _FakeElement:
    def __init__(self, value):
        self.value = value


class _FakeSession:
    """Replaces the headless session, so each incomplete state is direct."""

    def __init__(self, *, exception=(), error=(), state=None):
        self.exception = [_FakeElement(value) for value in exception]
        self.error = [_FakeElement(value) for value in error]
        self.session_state = dict(state or {})

    def run(self):
        return self


def _install_fake_session(monkeypatch, session):
    import streamlit.testing.v1 as testing

    started = []

    class FakeAppTest:
        @staticmethod
        def from_file(path, default_timeout):
            started.append((path, default_timeout, os.environ.get("SECTOR_AUTOSAVE_DIR")))
            return session

    monkeypatch.setattr(testing, "AppTest", FakeAppTest)
    return started


_LOADED = {"_project_msg": ("success", "Project loaded")}


@pytest.mark.parametrize(
    ("session", "error", "detail"),
    [
        (dict(exception=["stop"]), RuntimeError, "The project input build stopped: stop"),
        (dict(state={}), ValueError, "Sector did not confirm the project load"),
        (
            dict(state=_LOADED, error=["Enter a positive bar area"]),
            ValueError,
            "Correct the project inputs: Enter a positive bar area",
        ),
        (dict(state=_LOADED), RuntimeError, "The project input build gave no inputs"),
    ],
    ids=["exception", "no-load-message", "input-error", "no-inputs"],
)
def test_project_inputs_fails_closed_for_each_incomplete_session(
    monkeypatch, session, error, detail,
):
    fake = _FakeSession(**session)
    started = _install_fake_session(monkeypatch, fake)
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "kept-folder")
    with pytest.raises(error, match=re.escape(detail)):
        calculation_service.project_inputs("project text")
    assert fake.session_state["_pending_project"] == "project text"
    assert started[0][0] == APP
    assert started[0][2] not in {None, "kept-folder"}
    assert os.environ["SECTOR_AUTOSAVE_DIR"] == "kept-folder"


def test_project_inputs_accepts_parsed_tables_and_scalars(monkeypatch):
    tables, scalars = project_io.parse_project(reproducible_example.project_json())
    inputs = {"section": None}
    fake = _FakeSession(state=dict(_LOADED, _latest_inputs=inputs))
    _install_fake_session(monkeypatch, fake)
    monkeypatch.delenv("SECTOR_AUTOSAVE_DIR", raising=False)
    assert calculation_service.project_inputs((tables, scalars)) is inputs
    # The save time of a project text has a resolution of 1 s, so compare the
    # documents without it.
    assert _without_save_time(fake.session_state["_pending_project"]) == (
        _without_save_time(project_io.dump_project(tables, scalars))
    )
    assert "SECTOR_AUTOSAVE_DIR" not in os.environ


def _without_save_time(text: str) -> dict:
    document = json.loads(text)
    del document["provenance"]["saved_at_utc"]
    return document


def test_command_line_rejects_a_missing_file_with_one_line(tmp_path, capsys):
    missing = tmp_path / "missing.json"
    assert calculation_service.main([str(missing)]) == 1
    captured = capsys.readouterr()
    assert captured.err == (
        f"Sector: The file {missing} does not exist. Make sure that the path "
        "is correct.\n"
    )
    assert captured.out == ""


@pytest.mark.parametrize("kind", ["folder", "not-utf-8"])
def test_command_line_rejects_an_unreadable_file_with_one_line(tmp_path, capsys, kind):
    if kind == "folder":
        target = tmp_path / "project-folder"
        target.mkdir()
    else:
        target = tmp_path / "binary.json"
        target.write_bytes(b"\xff\xfe\x00\x81")
    assert calculation_service.main([str(target)]) == 1
    assert capsys.readouterr().err == (
        f"Sector: Cannot read the project file: {target}. Make sure that it "
        "is a Sector project file that you can open.\n"
    )


def test_command_line_prints_the_engineer_message_of_a_validation_error(
    monkeypatch, tmp_path, capsys,
):
    from sector.engineer_message import EngineerMessage

    message = EngineerMessage("TEST-CODE", "Increase the sweep increment")

    def rejected(_inputs, **_kwargs):
        raise calculation_service.engineer_messages.EngineerValidationError(message)

    monkeypatch.setattr(
        calculation_service, "project_inputs", lambda _text: {"section": None}
    )
    monkeypatch.setattr(calculation_service, "run_analysis", rejected)
    path = tmp_path / "project.json"
    path.write_text("{}", encoding="utf-8")
    assert calculation_service.main([str(path)]) == 1
    assert capsys.readouterr().err.strip() == "Sector: Increase the sweep increment"


def test_script_entry_starts_without_an_installed_package():
    result = subprocess.run(
        [sys.executable, "-I", str(SERVICE), "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Calculate one Sector project file" in result.stdout


def _run_command_line(path, tmp_path):
    # A new process, as the engineer runs it, with its own autosave folder.
    environment = dict(os.environ, SECTOR_AUTOSAVE_DIR=str(tmp_path / "autosave"))
    return subprocess.run(
        [sys.executable, "-I", str(SERVICE), str(path)],
        cwd=ROOT, capture_output=True, text=True, timeout=600, check=False,
        env=environment,
    )


def test_command_line_writes_one_line_for_a_rejected_project(tmp_path):
    path = tmp_path / "not-a-project.json"
    path.write_text("{", encoding="utf-8")
    result = _run_command_line(path, tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Sector: New file was not applied: the selected file is not a readable "
        "Sector project. Select an intact, compatible Sector project file and "
        "try again.\n"
    )


def test_command_line_summary_restores_the_log_state(monkeypatch, tmp_path, capsys):
    inp = report_render_fixture._inputs()
    expected = project_io.result_sha256(sector_app.run_analysis(copy.deepcopy(inp)))
    monkeypatch.setattr(calculation_service, "project_inputs", lambda _text: inp)
    path = tmp_path / "fixture.json"
    path.write_text("{}", encoding="utf-8")
    import logging

    before = logging.root.manager.disable
    assert calculation_service.main([str(path)]) == 0
    assert logging.root.manager.disable == before
    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == "Project: fixture.json"
    assert f"Result SHA-256: {expected}" in printed


def test_command_line_result_equals_the_calculate_record_of_the_app(tmp_path):
    text = reproducible_example.project_json()
    path = tmp_path / "reference.json"
    path.write_text(text, encoding="utf-8")
    result = _run_command_line(path, tmp_path)
    assert result.returncode == 0, result.stderr
    # A valid project writes nothing to standard error (no internal log lines).
    assert result.stderr == ""
    printed = result.stdout.splitlines()
    assert printed[0] == "Project: reference.json"
    service_hash = next(
        line.split(": ", 1)[1] for line in printed if line.startswith("Result SHA-256")
    )

    at = AppTest.from_file(APP, default_timeout=300)
    at.session_state["_pending_project"] = text
    at.run()
    assert not at.exception
    at.session_state["_main_page"] = "Analysis"
    at.session_state["_next_workflow_page"] = "results"
    at.run()
    at.button(key="calculate").click().run(timeout=300)
    assert not at.exception
    record = at.session_state["calculation_record"]
    assert record["result_sha256"] == service_hash
    assert project_io.result_sha256(at.session_state["results"]) == service_hash
    rows = [line for line in printed if line.startswith("  ")]
    assert rows and all(":" in line for line in rows)
    assert [line.split(":")[0] for line in printed[-2:]] == [
        "Input build time", "Calculation time",
    ]
