"""0.97.1 F2 (AR-07): the calculation service module and its headless entry.

The calculation functions moved unchanged from ``app/sector_app.py`` to
``app/calculation_service.py``. These tests hold the module contract: the
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
    script = (
        "import sys\n"
        f"sys.path[:0] = [{str(ROOT)!r}, {str(ROOT / 'app')!r}]\n"
        "from app import calculation_service\n"
        "loaded = sorted(m for m in sys.modules if m.split('.')[0] == 'streamlit')\n"
        "print(len(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"


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


@pytest.mark.parametrize("item", [3, (1, 2, 3), b"{}"])
def test_calculate_project_rejects_an_item_that_is_not_a_project(item):
    with pytest.raises(TypeError, match="project must be"):
        calculation_service.calculate_project(item)


def test_invalid_section_gives_an_empty_result_set_and_summary_message():
    inp = report_render_fixture._inputs()
    inp["geometry_error"] = "The outline crosses itself"
    result_set = calculation_service.calculate_project(inp)
    assert result_set["results"] == {}
    assert calculation_service._summary_lines("p.json", result_set, 0.0) == [
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
    assert fake.session_state["_pending_project"] == project_io.dump_project(
        tables, scalars
    )
    assert "SECTOR_AUTOSAVE_DIR" not in os.environ


def test_command_line_rejects_a_missing_file(tmp_path, capsys):
    assert calculation_service.main([str(tmp_path / "missing.json")]) == 1
    assert "Sector:" in capsys.readouterr().err


def test_command_line_prints_the_engineer_message_of_a_validation_error(
    monkeypatch, tmp_path, capsys,
):
    from sector.engineer_message import EngineerMessage

    message = EngineerMessage("TEST-CODE", "Increase the sweep increment")

    def rejected(_project):
        raise calculation_service.engineer_messages.EngineerValidationError(message)

    monkeypatch.setattr(calculation_service, "calculate_project", rejected)
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


def test_command_line_result_equals_the_calculate_record_of_the_app(
    tmp_path, capsys,
):
    text = reproducible_example.project_json()
    path = tmp_path / "reference.json"
    path.write_text(text, encoding="utf-8")
    assert calculation_service.main([str(path)]) == 0
    printed = capsys.readouterr().out.splitlines()
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
