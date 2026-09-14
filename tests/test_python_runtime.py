"""Fast runtime selection checks without creating a build environment."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools import build_portable_windows as portable

ROOT = Path(__file__).resolve().parents[1]


def test_ci_uses_the_exact_source_pin():
    assert (ROOT / ".python-version").read_text("ascii").strip() == "3.13.15"
    workflow = yaml.safe_load((ROOT / ".github/workflows/qa.yml").read_text("utf-8"))
    selectors = [
        step["with"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/setup-python@")
    ]
    assert len(selectors) == 3
    assert all(item["python-version-file"] == ".python-version" for item in selectors)


def test_direct_driver_accepts_the_pinned_running_interpreter():
    portable._validate_python(ROOT, Path(sys.executable))


@pytest.mark.parametrize(
    "identity",
    [
        "CPython|3.13.0|64",
        "CPython|3.14.0|64",
        "PyPy|3.13.15|64",
        "CPython|3.13.15|32",
        "",
    ],
)
def test_direct_driver_rejects_incompatible_interpreters(monkeypatch, identity):
    monkeypatch.setattr(
        portable.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, identity, ""),
    )
    with pytest.raises(portable.PortableBuildError, match="64-bit CPython 3.13.15"):
        portable._validate_python(ROOT, Path(sys.executable))


@pytest.mark.parametrize("pin", ["3.13", "3.13.15rc1", "3.14.0", "3.13.015", ""])
def test_driver_rejects_invalid_source_pin_before_probing(tmp_path, pin):
    (tmp_path / ".python-version").write_text(pin, encoding="ascii")
    with pytest.raises(portable.PortableBuildError, match="exact Python 3.13 patch"):
        portable._validate_python(tmp_path, tmp_path / "unavailable.exe")


def test_driver_reports_failed_probe(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("unusable interpreter")

    monkeypatch.setattr(portable.subprocess, "run", fail)
    with pytest.raises(portable.PortableBuildError, match="cannot probe Python"):
        portable._validate_python(ROOT, Path(sys.executable))


@pytest.mark.skipif(os.name != "nt", reason="Windows build selector")
@pytest.mark.parametrize("valid_override", [True, False])
def test_powershell_selector_checks_explicit_override_without_fallback(
    tmp_path, valid_override
):
    # Execute the actual selector definitions, stopping before the build driver.
    script_path = ROOT / "packaging/build_portable.ps1"
    script = script_path.read_text("utf-8").split("$python = Resolve-SectorPython", 1)[
        0
    ]
    script = script.replace(
        "$sourceRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))",
        "$sourceRoot = $env:SECTOR_TEST_SOURCE",
    )
    script += "\n$selected = Resolve-SectorPython\nWrite-Output $selected.Executable\n"
    harness = tmp_path / "selector.ps1"
    harness.write_text(script, encoding="utf-8")
    environment = dict(os.environ)
    environment["SECTOR_TEST_SOURCE"] = str(ROOT)
    environment["SECTOR_PORTABLE_PYTHON"] = (
        sys.executable if valid_override else str(tmp_path / "missing-python.exe")
    )
    result = subprocess.run(
        [
            shutil.which("powershell.exe"),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        timeout=30,
    )
    if valid_override:
        assert result.returncode == 0, result.stderr
        assert Path(result.stdout.strip()).resolve() == Path(sys.executable).resolve()
    else:
        assert result.returncode != 0
        assert (
            "SECTOR_PORTABLE_PYTHON must select 64-bit CPython 3.13.15" in result.stderr
        )
