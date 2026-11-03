from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from tools import qa_core_shards


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"
MARKER = "pytest.mark.real_image_export"
XDIST_GROUP = "publication-real-figures"

DIRECT_EXPORT_TESTS = {
    "tests/test_viz.py::test_oblique_concave_map_leaves_open_recess_pixels_empty",
    "tests/test_viz.py::test_report_and_app_size_shear_callout_borders_have_pixel_gaps",
    "tests/test_viz.py::test_report_size_tall_axis_x_callouts_are_contained_and_separate",
    "tests/test_viz.py::test_report_size_wide_axis_y_callouts_are_contained_and_separate",
    "tests/test_viz.py::test_report_size_wide_axis_x_tension_face_clears_section",
    "tests/test_viz.py::test_report_size_tall_axis_y_tension_face_clears_section",
}
INDIRECT_EXPORT_TESTS = {
    "tests/test_manual_rendered.py::test_issued_manual_renders_every_page_and_retains_navigation",
    "tests/test_report_rendered.py::test_issued_report_renders_every_page_and_retains_expected_content",
}


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _function_inventory(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    top_level = tuple(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    all_functions = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return top_level, all_functions


def _node_id(path: Path, function: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    return f"{path.relative_to(ROOT).as_posix()}::{function.name}"


def _has_marker(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return MARKER in {_dotted_name(item) for item in function.decorator_list}


def _has_publication_xdist_group(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if _dotted_name(decorator) != "pytest.mark.xdist_group":
            continue
        name = next(
            (keyword.value for keyword in decorator.keywords if keyword.arg == "name"),
            None,
        )
        if isinstance(name, ast.Constant) and name.value == XDIST_GROUP:
            return True
    return False


def _calls_real_export(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"to_image", "write_image"}
        for node in ast.walk(function)
    )


def _calls_real_fixture(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Treat an issued fixture as real unless it explicitly disables figures."""

    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if _dotted_name(node.func).split(".")[-1] != "build_fixture_pdf":
            continue
        figures = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "figures"),
            None,
        )
        if not (
            isinstance(figures, ast.Constant)
            and figures.value is False
        ):
            return True
    return False


def test_every_real_browser_export_test_has_the_registered_marker():
    direct = set()
    indirect = set()
    marked = set()
    functions = {}
    for path in sorted(TESTS.glob("test_*.py")):
        top_level, all_functions = _function_inventory(path)
        # Keep real browser calls directly owned by test functions. A new helper
        # containing to_image/write_image must first be routed into this policy
        # instead of silently escaping the marker inventory.
        exporter_owners = {
            _node_id(path, function)
            for function in all_functions
            if _calls_real_export(function)
        }
        assert all("::test_" in owner for owner in exporter_owners)
        direct.update(exporter_owners)

        for function in top_level:
            if not function.name.startswith("test_"):
                continue
            node_id = _node_id(path, function)
            functions[node_id] = function
            if _calls_real_fixture(function):
                indirect.add(node_id)
            if _has_marker(function):
                marked.add(node_id)

    assert direct == DIRECT_EXPORT_TESTS
    assert indirect == INDIRECT_EXPORT_TESTS
    assert direct | indirect <= set(functions)
    assert direct | INDIRECT_EXPORT_TESTS == marked
    assert all(_has_publication_xdist_group(functions[node_id]) for node_id in direct)
    assert "real_image_export:" in (ROOT / "pytest.ini").read_text(encoding="utf-8")


def test_real_image_workflow_runs_every_marked_family_in_a_fresh_serial_process(tmp_path, monkeypatch):
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    core_job = workflow["jobs"]["core"]
    assert core_job["strategy"]["matrix"]["shard"] == list(qa_core_shards.SHARDS)
    core_step = next(step for step in core_job["steps"] if step["name"] == "Run complete primary shard")
    assert core_step["run"] == 'python tools/qa_core_shards.py run --shard "${{ matrix.shard }}" --output qa-shard'
    assert workflow["jobs"]["test"]["needs"] == "core"
    commands = {}
    monkeypatch.setattr(qa_core_shards, "identity", lambda: {"run_id": "1", "run_attempt": "1"})
    monkeypatch.setattr(qa_core_shards, "source_digest", lambda: "unchanged-fixture-source")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "temporary"))
    for shard in core_job["strategy"]["matrix"]["shard"]:
        def capture(command, shard=shard, **kwargs):
            commands.setdefault(shard, []).append((command, kwargs["env"]))
            return SimpleNamespace(returncode=0)
        monkeypatch.setattr(qa_core_shards.subprocess, "run", capture)
        assert qa_core_shards.run_shard(shard, tmp_path / shard) == 0
    temps = []
    for shard in qa_core_shards.SHARDS[:-1]:
        [(command, environment)] = commands[shard]
        assert command[1:3] == ["-m", "pytest"]
        assert command[command.index("-n") + 1] == "4"
        assert command[command.index("--dist") + 1] == "loadgroup"
        assert environment["SECTOR_QA_SHARD"] == shard
        if shard.startswith("core-"):
            assert command[3:6] == ["tests", "-m", "not real_image_export"]
            assert "--cov=app" in command and "--cov=sector" in command and "--cov-branch" not in command
        else:
            assert "-m" not in command[3:] and "--cov-branch" in command
        temps.append(command[command.index("--basetemp") + 1])

    real = commands["real"]
    output = tmp_path / "real"
    selections = (
        ["tests/test_viz.py"],
        ["tests/test_report_rendered.py::test_issued_report_renders_every_page_and_retains_expected_content"],
        ["tests/test_manual_rendered.py::test_issued_manual_renders_every_page_and_retains_navigation"],
    )
    assert len(real) == 5
    for (command, environment), selection, name in zip(real, selections, ("viz", "report", "manual")):
        assert command[1:3] == ["-m", "pytest"]
        assert command[3:4] == selection
        assert command[command.index("-n") + 1] == "0"
        assert command[command.index("-m", 3) + 1] == "real_image_export"
        assert command.count("--cov-append") == 1 and "--cov=app" in command and "--cov=sector" in command
        assert f"--junitxml={output.resolve() / f'test-results-real-{name}.xml'}" in command
        assert environment["COVERAGE_FILE"] == str(output.resolve() / ".coverage")
        assert "SECTOR_QA_SHARD" not in environment
        basetemp = Path(command[command.index("--basetemp") + 1])
        assert basetemp.name == f"real-{name}"
        temps.append(str(basetemp))
    assert [command[1:] for command, _ in real[3:]] == [
        ["tools/report_render_fixture.py", "--output", str(output.resolve() / "report")],
        ["tools/manual_render_fixture.py", "--output", str(output.resolve() / "manual")],
    ]
    assert len(set(temps)) == len(temps) == len(qa_core_shards.SHARDS) + 2
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phases"] == dict.fromkeys(qa_core_shards.REAL_PHASES, 0)
