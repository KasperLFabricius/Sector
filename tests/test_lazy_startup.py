"""PR-14B lazy-startup and immediate launcher-feedback contract."""

from __future__ import annotations

import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
SECTOR_INIT = ROOT / "sector" / "__init__.py"
SECTOR_APP = APP / "sector_app.py"
LAUNCHER = ROOT / "packaging" / "run_sector.py"

EXPECTED_EXPORTS = {
    "AreaMoments": ("geometry", "AreaMoments"),
    "area_moments": ("geometry", "area_moments"),
    "area_moments_rings": ("geometry", "area_moments_rings"),
    "clip_halfplane": ("geometry", "clip_halfplane"),
    "orient": ("geometry", "orient"),
    "signed_area": ("geometry", "signed_area"),
    "Bar": ("section", "Bar"),
    "Section": ("section", "Section"),
    "Concrete": ("materials", "Concrete"),
    "MildSteel": ("materials", "MildSteel"),
    "Prestress": ("materials", "Prestress"),
    "ElasticResult": ("elastic", "ElasticResult"),
    "CombinedElasticResult": ("elastic", "CombinedElasticResult"),
    "solve_elastic": ("elastic", "solve_elastic"),
    "solve_elastic_combined": ("elastic", "solve_elastic_combined"),
    "SpectrumBin": ("fatigue", "SpectrumBin"),
    "ReinforcementFatigueProperties": (
        "fatigue",
        "ReinforcementFatigueProperties",
    ),
    "ConcreteFatigueProperties": ("fatigue", "ConcreteFatigueProperties"),
    "ConcreteFibreSearch": ("fatigue", "ConcreteFibreSearch"),
    "FatigueSpectrumResult": ("fatigue", "FatigueSpectrumResult"),
    "steel_fatigue_life": ("fatigue", "steel_fatigue_life"),
    "concrete_fatigue_strength": ("fatigue", "concrete_fatigue_strength"),
    "concrete_fatigue_life": ("fatigue", "concrete_fatigue_life"),
    "concrete_equivalent_utilisation": (
        "fatigue",
        "concrete_equivalent_utilisation",
    ),
    "locate_governing_concrete_fibre": (
        "fatigue",
        "locate_governing_concrete_fibre",
    ),
    "analyse_fatigue_spectrum": ("fatigue", "analyse_fatigue_spectrum"),
    "analyse_grouped_spectra": ("fatigue", "analyse_grouped_spectra"),
    "PlasticPoint": ("plastic", "PlasticPoint"),
    "plastic_capacity_at_angle": ("plastic", "plastic_capacity_at_angle"),
    "solve_plastic": ("plastic", "solve_plastic"),
    "InteractionPoint": ("plastic", "InteractionPoint"),
    "solve_interaction": ("plastic", "solve_interaction"),
}

EXPECTED_MODULES = (
    "build_info",
    "capacity",
    "codes",
    "combined",
    "design_standards",
    "detailing",
    "elastic",
    "fatigue",
    "geometry",
    "kernels",
    "material_presets",
    "materials",
    "plastic",
    "section",
    "serviceability",
    "shear",
    "sls",
    "templates",
    "torsion",
)


def _run_isolated(
    source: str, *, no_site: bool = False, inherit_site: bool = False, env=None
):
    command = [sys.executable]
    if not inherit_site:
        command.append("-I")
    if no_site:
        command.append("-S")
    command.extend(["-c", source])
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def _assert_process_ok(result: subprocess.CompletedProcess):
    assert result.returncode == 0, (
        f"isolated process failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_bare_sector_import_is_stdlib_only_and_does_not_load_solvers():
    source = f"""
import json
import sys
sys.path.insert(0, {str(ROOT)!r})
import sector
for name in (
    'numpy', 'numba', 'sector.elastic', 'sector.fatigue', 'sector.geometry',
    'sector.kernels', 'sector.materials', 'sector.plastic', 'sector.section',
):
    assert name not in sys.modules, name
assert sector.__version__ == '0.96.1'
assert tuple(sector.__all__) == {tuple(EXPECTED_EXPORTS)!r}
print(json.dumps({{'version': sector.__version__, 'exports': len(sector.__all__)}}))
"""
    result = _run_isolated(source, no_site=True)
    _assert_process_ok(result)
    assert json.loads(result.stdout) == {"exports": 32, "version": "0.96.1"}


def test_lazy_public_registry_is_complete_ordered_and_explicit():
    import sector

    assert sector.__all__ == list(EXPECTED_EXPORTS)
    assert sector._EXPORTS == EXPECTED_EXPORTS
    assert tuple(sector._MODULES) == EXPECTED_MODULES
    assert sector._MODULES == {name: name for name in EXPECTED_MODULES}


def test_every_public_export_and_submodule_resolves_to_authoritative_object():
    import sector

    for name, (module_name, attribute) in EXPECTED_EXPORTS.items():
        expected = getattr(importlib.import_module(f"sector.{module_name}"), attribute)
        first = getattr(sector, name)
        assert first is expected
        assert getattr(sector, name) is first
    for name in EXPECTED_MODULES:
        expected = importlib.import_module(f"sector.{name}")
        assert getattr(sector, name) is expected
    with pytest.raises(AttributeError, match="has no attribute"):
        getattr(sector, "not_an_advertised_sector_name")


def test_capacity_and_detailing_import_without_solver_or_kernel_modules():
    source = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
import sector.capacity
import sector.detailing
for name in ('sector.elastic', 'sector.fatigue', 'sector.kernels', 'sector.plastic'):
    assert name not in sys.modules, name
"""
    result = _run_isolated(source, inherit_site=True)
    _assert_process_ok(result)


def test_capacity_keeps_replaceable_lazy_plastic_solver_seams():
    source = f"""
import sys
import types
sys.path.insert(0, {str(ROOT)!r})
from sector import capacity
fake = types.ModuleType('sector.plastic')
fake.plastic_capacity_at_angle = lambda *args, **kwargs: ('point', args, kwargs)
fake.conditional_capacity = lambda *args, **kwargs: ('conditional', args, kwargs)
fake.FACE_ANGLE = {{('x', True): 90.0}}
sys.modules['sector.plastic'] = fake
assert capacity.plastic_capacity_at_angle(1, value=2) == (
    'point', (1,), {{'value': 2}}
)
assert capacity.conditional_capacity(3) == ('conditional', (3,), {{}})
assert capacity._face_angle('x', True) == 90.0
"""
    result = _run_isolated(source)
    _assert_process_ok(result)


def _deferred_import_module():
    sys.path.insert(0, str(APP))
    try:
        return importlib.import_module("deferred_import")
    finally:
        sys.path.remove(str(APP))


def test_deferred_module_repr_and_dir_are_inert_then_cache_first_use(
    tmp_path, monkeypatch
):
    deferred_import = _deferred_import_module()
    module_name = "pr14b_deferred_fixture"
    (tmp_path / f"{module_name}.py").write_text(
        "identity = object()\nvalue = 17\n", encoding="ascii"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(module_name, None)

    proxy = deferred_import.deferred_module(module_name)
    assert proxy.module_name == module_name
    assert not proxy.loaded
    assert "deferred" in repr(proxy)
    assert dir(proxy) == ["loaded", "module_name"]
    assert module_name not in sys.modules

    assert proxy.value == 17
    module = sys.modules[module_name]
    assert proxy.identity is module.identity
    assert proxy.loaded
    assert "loaded" in repr(proxy)


def test_deferred_module_does_not_cache_failed_import(monkeypatch):
    deferred_import = _deferred_import_module()
    expected = types.ModuleType("retry_target")
    expected.answer = 42
    calls = []

    def import_once_available(name):
        calls.append(name)
        if len(calls) == 1:
            raise ModuleNotFoundError(name)
        return expected

    monkeypatch.setattr(deferred_import, "import_module", import_once_available)
    proxy = deferred_import.DeferredModule("retry_target")
    with pytest.raises(ModuleNotFoundError):
        proxy.answer
    assert not proxy.loaded
    assert proxy.answer == 42
    assert proxy.loaded
    assert calls == ["retry_target", "retry_target"]


def test_default_app_run_leaves_hidden_heavy_families_unloaded(tmp_path):
    absent = (
        "fatigue_analysis",
        "fatigue_presentation",
        "result_presentation",
        "viz",
        "sector.combined",
        "sector.elastic",
        "sector.fatigue",
        "sector.kernels",
        "sector.plastic",
        "sector.serviceability",
        "sector.shear",
        "sector.sls",
        "sector.torsion",
    )
    source = f"""
import json
import pathlib
import sys
from streamlit.testing.v1 import AppTest
root = pathlib.Path({str(ROOT)!r})
at = AppTest.from_file(str(root / 'app' / 'sector_app.py'), default_timeout=30)
at.run(timeout=30)
assert not at.exception, [str(item.value) for item in at.exception]
absent = {absent!r}
loaded = [name for name in absent if name in sys.modules]
assert not loaded, loaded
print(json.dumps({{'absent': len(absent)}}))
"""
    env = os.environ.copy()
    env["SECTOR_AUTOSAVE_DIR"] = str(tmp_path / "autosave")
    env["TEMP"] = str(tmp_path)
    env["TMP"] = str(tmp_path)
    result = _run_isolated(source, inherit_site=True, env=env)
    _assert_process_ok(result)
    assert json.loads(result.stdout) == {"absent": len(absent)}


def test_app_deferred_contract_and_fatigue_method_identity_are_pinned():
    source = SECTOR_APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    eager_names = {
        "case_analysis",
        "fatigue_analysis",
        "fatigue_inputs",
        "fatigue_presentation",
        "load_cases",
        "material_catalog",
        "project_io",
        "reinforcement_table",
        "result_presentation",
        "session_state_migrations",
        "app.modelled_direction",
        "app.table_field_definitions",
        "viz",
    }
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert eager_names.isdisjoint(imported)
    for name in eager_names:
        assert f'deferred_module("{name}")' in source

    from sector import fatigue

    expected = (
        fatigue.CONCRETE_MINER,
        fatigue.CONCRETE_PROJECT_MINER,
        fatigue.CONCRETE_EQUIVALENT,
    )
    assignments = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and target.id.startswith("_FATIGUE_CONCRETE_")
        and not isinstance(node.value, (ast.Tuple, ast.List))
    }
    assert assignments["_FATIGUE_CONCRETE_MINER"] == expected[0]
    assert assignments["_FATIGUE_CONCRETE_PROJECT_MINER"] == expected[1]
    assert assignments["_FATIGUE_CONCRETE_EQUIVALENT"] == expected[2]


def test_launcher_prints_progress_before_importing_streamlit():
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    main = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    first = main.body[0]
    assert isinstance(first, ast.Expr)
    assert isinstance(first.value, ast.Call)
    assert isinstance(first.value.func, ast.Name)
    assert first.value.func.id == "print"
    assert ast.literal_eval(first.value.args[0]) == (
        "Starting Sector; the local browser will open when the interface is ready."
    )
    assert any(
        keyword.arg == "flush" and ast.literal_eval(keyword.value) is True
        for keyword in first.value.keywords
    )
    streamlit_imports = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("streamlit")
    ]
    assert streamlit_imports
    assert all(node.lineno > first.lineno for node in streamlit_imports)
