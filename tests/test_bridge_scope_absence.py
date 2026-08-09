"""End-to-end absence guard for the retired component-mapped bridge workflows."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

RETIRED_PROJECT_KEYS = (
    "bridge_standard",
    "bridge_brittle_base",
    "bridge_box_walls_base",
    "bridge_minimum_crack_base",
)

LIVE_SURFACES = (
    ROOT / "app" / "sector_app.py",
    ROOT / "app" / "project_io.py",
    ROOT / "app" / "sector_report.py",
    ROOT / "app" / "manual.py",
    ROOT / "app" / "reproducible_example.py",
    ROOT / "README.md",
)

PUBLICATION_FIXTURES = (
    ROOT / "tools" / "report_render_fixture.py",
    ROOT / "tools" / "manual_render_fixture.py",
)


def test_retired_component_inputs_are_absent_from_live_product_surfaces():
    for path in LIVE_SURFACES:
        source = path.read_text(encoding="utf-8")
        for key in RETIRED_PROJECT_KEYS:
            assert key not in source, f"{key} survived in {path.relative_to(ROOT)}"
        for phrase in (
            "Optional bridge calculations",
            "Selected bridge method family",
            "Optional brittle Method B",
            "Box-wall shear and torsion",
            "Web/flange minimum crack reinforcement",
        ):
            assert phrase not in source, (
                f"{phrase!r} survived in {path.relative_to(ROOT)}"
            )


def test_no_fictitious_second_generation_part_2_is_exposed():
    for path in (*LIVE_SURFACES, *PUBLICATION_FIXTURES):
        source = path.read_text(encoding="utf-8")
        assert "EN 1992-2:2023" not in source
        assert "DS/EN 1992-2:2023" not in source


def test_streamlit_has_only_a_hot_reload_alias_for_the_retired_view():
    path = ROOT / "app" / "sector_app.py"
    source = path.read_text(encoding="utf-8")
    assert source.count('"Bridge Calculations"') == 1
    assert '"Bridge Calculations": "Results Overview"' in source
    function_names = {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "bridge_view" not in function_names
    assert "_run_bridge_or_invalid" not in function_names


def test_bridge_input_adapter_module_is_removed():
    assert not (ROOT / "app" / "bridge_inputs.py").exists()
