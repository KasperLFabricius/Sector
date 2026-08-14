from __future__ import annotations

import ast
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"
MARKER = "pytest.mark.real_image_export"
XDIST_GROUP = "publication-real-figures"

DIRECT_EXPORT_TESTS = {
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


def test_real_image_workflow_runs_every_marked_family_in_a_fresh_serial_process():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    coverage_step = next(
        step
        for step in workflow["jobs"]["test"]["steps"]
        if step["name"] == "Run complete test suite with coverage"
    )
    command = coverage_step["run"]

    phases = (
        'python -m pytest tests -n 4 `\n  --dist loadgroup `\n  -m "not real_image_export"',
        'python -m pytest tests/test_viz.py -n 0 `\n  -m "real_image_export"',
        "python -m pytest `\n  tests/test_report_rendered.py::"
        "test_issued_report_renders_every_page_and_retains_expected_content `",
        "python -m pytest `\n  tests/test_manual_rendered.py::"
        "test_issued_manual_renders_every_page_and_retains_navigation `",
    )
    positions = [command.index(phase) for phase in phases]

    assert positions == sorted(positions)
    assert command.count("python -m pytest") == 4
    assert command.count("-n 0") == 3
    assert command.count("--cov-append") == 3
    for folder, variable in (
        ("real-viz", "$vizTemp"),
        ("real-report", "$reportTemp"),
        ("real-manual", "$manualTemp"),
    ):
        assert f'{variable} = Join-Path $baseTemp "{folder}"' in command
        assert f"--basetemp {variable}" in command
    assert command.index("coverage xml") > positions[-1]
    assert command.index("coverage report") > command.index("coverage xml")
    assert "--fail-under=90" in command
