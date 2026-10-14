"""The portable light theme follows the shipped configuration authority."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def launcher():
    spec = importlib.util.spec_from_file_location(
        "theme_test_launcher", ROOT / "packaging" / "run_sector.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bundle(tmp_path, monkeypatch, launcher):
    base = tmp_path / "frozen bundle with spaces"
    config = base / ".streamlit" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_bytes((ROOT / ".streamlit" / "config.toml").read_bytes())
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher.sys, "_MEIPASS", str(base), raising=False)
    return base, config


def _flags(launcher):
    return dict(flag[2:].split("=", 1) for flag in launcher._theme_argv())


def test_every_authored_light_property_has_exact_root_and_variant_authority(launcher):
    theme = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["theme"]
    common = {key: value for key, value in theme.items() if key not in {"base", "sidebar"}}
    sidebar = {**common, **theme["sidebar"]}
    expected = {"theme.base": "light"}
    for section, values in (
        ("theme", common), ("theme.light", common),
        ("theme.sidebar", sidebar), ("theme.light.sidebar", sidebar),
    ):
        expected.update({section + "." + key: value for key, value in values.items()})
    assert _flags(launcher) == expected
    assert len(expected) == 33
    assert not any(key.startswith("theme.dark") for key in expected)


def test_bundle_resolution_ignores_cwd_without_mutating_environment(bundle, launcher, tmp_path, monkeypatch):
    cwd = tmp_path / "unrelated working directory"
    (cwd / ".streamlit").mkdir(parents=True)
    (cwd / ".streamlit" / "config.toml").write_text('[theme]\nprimaryColor="#ff0000"\n')
    monkeypatch.chdir(cwd)
    before = dict(os.environ)
    assert _flags(launcher)["theme.primaryColor"] == "#176b75"
    assert Path.cwd() == cwd
    assert dict(os.environ) == before
    assert launcher._bundle_base() == bundle[0]


@pytest.mark.parametrize("change", [
    "missing", "malformed", "no-theme", "no-sidebar", "extra-key",
    "extra-sidebar", "empty-value", "wrong-type", "wrong-base",
])
def test_invalid_bundled_theme_fails_clearly(bundle, launcher, change):
    _, path = bundle
    source = path.read_text()
    replacements = {
        "malformed": "[theme", "no-theme": "[server]\nport=8502\n",
        "no-sidebar": source.split("[theme.sidebar]")[0],
        "extra-key": source.replace('[theme]\n', '[theme]\nunknown="x"\n'),
        "extra-sidebar": source + '\nunknown="x"\n',
        "empty-value": source.replace('font = "sans-serif"', 'font = ""'),
        "wrong-type": source.replace('font = "sans-serif"', 'font = 7'),
        "wrong-base": source.replace('base = "light"', 'base = "dark"'),
    }
    if change == "missing":
        path.unlink()
    else:
        path.write_text(replacements[change])
    with pytest.raises((ValueError, FileNotFoundError)):
        launcher._theme_argv()


def test_existing_launch_flags_keep_their_authority(bundle, launcher):
    _, path = bundle
    path.write_text(path.read_text().replace('address = "127.0.0.1"', 'address = "0.0.0.0"').replace('gatherUsageStats = false', 'gatherUsageStats = true'))
    argv = launcher._streamlit_argv("app.py", "62801", headless=True)
    assert [arg for arg in argv if not arg.startswith("--theme.")] == [
        "streamlit", "run", "app.py", "--server.port=62801",
        "--server.address=127.0.0.1", "--global.developmentMode=false",
        "--server.headless=true", "--server.fileWatcherType=none",
        "--server.runOnSave=false", "--browser.gatherUsageStats=false",
        "--client.toolbarMode=viewer", "--client.showErrorDetails=type",
    ]


def test_actual_parser_and_browser_protobuf_preserve_light_authority(bundle, launcher, tmp_path, monkeypatch):
    from streamlit import config, file_util
    from streamlit.proto.NewSession_pb2 import CustomThemeConfig
    from streamlit.runtime.app_session import _populate_theme_msg
    from streamlit.web import cli

    cwd = tmp_path / "conflicting cwd"
    (cwd / ".streamlit").mkdir(parents=True)
    common = 'primaryColor="#abcdef"\nbackgroundColor="#112233"\nfont="serif"\n'
    (cwd / ".streamlit" / "config.toml").write_text(
        "".join("[" + section + "]\n" + common for section in (
            "theme", "theme.sidebar", "theme.light", "theme.light.sidebar", "theme.dark",
        ))
    )
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(file_util, "get_streamlit_file_path", lambda name: str(tmp_path / "isolated home" / name))
    monkeypatch.setattr(config, "_config_options", None)
    app = bundle[0] / "app.py"
    app.write_text("# Parser target. Never executed.\n")
    monkeypatch.setattr(config, "_main_script_path", str(app))
    argv = launcher._streamlit_argv(app, "62801", headless=True)
    ctx = cli.main.commands["run"].make_context("run", argv[2:])
    names = [arg[2:].split("=", 1)[0] for arg in argv[3:]]
    flags = {name: ctx.params[name.replace(".", "_")] for name in names}
    options = config.get_config_options(force_reparse=True, options_from_flags=flags)
    for section in ("theme", "theme.sidebar", "theme.light", "theme.light.sidebar"):
        msg = CustomThemeConfig()
        _populate_theme_msg(msg, section)
        assert msg.primary_color == "#176b75"
        assert msg.background_color == ("#eef3f5" if section.endswith("sidebar") else "#ffffff")
        assert msg.body_font == "sans-serif"
    assert options["server.address"].value == "127.0.0.1"
    assert options["browser.gatherUsageStats"].value is False
    assert options["theme.dark.primaryColor"].value == "#abcdef"


def test_config_is_a_required_build_source_and_shipped_data():
    import ast

    spec = ast.parse((ROOT / "packaging" / "sector.spec").read_text())
    assert any(isinstance(node, ast.Constant) and node.value == ".streamlit" for node in ast.walk(spec))
    assert '(os.path.join(ROOT, ".streamlit", "config.toml"), ".streamlit")' in (ROOT / "packaging" / "sector.spec").read_text()
    tree = ast.parse((ROOT / "tools" / "build_portable_windows.py").read_text())
    definition = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "_REQUIRED_SOURCE_PATHS" for target in node.targets))
    assert ".streamlit/config.toml" in ast.literal_eval(definition.value)
