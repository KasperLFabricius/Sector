"""Contract tests for building only from an exported exact commit tree."""

from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.build_exact_commit import (
    ExactBuildError,
    _build_environment,
    execute_exact_build,
    prepare_exact_build,
)

ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repository(tmp_path: Path):
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "sector-build@example.invalid")
    _git(root, "config", "user.name", "Sector build tests")
    _git(root, "config", "core.autocrlf", "false")
    files = {
        "requirements-build.txt": b"accepted-lock\n",
        "LICENSE": b"accepted-license\n",
        "tools/generate_third_party_notices.py": b"# accepted notices tool\n",
        "packaging/sector.spec": b"# accepted spec\n",
        "packaging/windows_version_info.txt": b"# accepted version resource\n",
        "packaging/run_sector.py": b"# accepted launcher\n",
        "app/sector_app.py": b"# accepted app\n",
        "sector/__init__.py": b'__version__ = "0.91"\n',
        "assets/sector.svg": b"<svg/>\n",
    }
    for relative, payload in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "accepted build fixture")
    return root, _git(root, "rev-parse", "HEAD"), files


def test_plan_exports_first_and_uses_only_exact_source_paths(tmp_path):
    root, commit, accepted = _repository(tmp_path)
    for relative in (
        "requirements-build.txt",
        "LICENSE",
        "tools/generate_third_party_notices.py",
        "packaging/sector.spec",
        "app/sector_app.py",
        "sector/__init__.py",
    ):
        (root / relative).write_bytes(b"hostile mutable worktree\n")
    output = tmp_path / "build-run"

    plan = prepare_exact_build(root, commit, output)

    assert plan.source_revision == commit
    assert plan.run_root == output.resolve()
    assert plan.source_root == output.resolve() / "source"
    for relative, payload in accepted.items():
        assert (plan.source_root / relative).read_bytes() == payload
    assert len(plan.commands) == 4
    assert plan.commands[0].arguments[-2] == "venv"
    assert plan.commands[0].arguments[-1] == str(
        plan.run_root / "build-environment"
    )
    assert plan.commands[1].arguments[-2:] == (
        "-r",
        str(plan.source_root / "requirements-build.txt"),
    )
    assert plan.commands[2].arguments[1] == str(
        plan.source_root / "tools" / "generate_third_party_notices.py"
    )
    assert "--requirements" in plan.commands[2].arguments
    assert "--tabulator-license" in plan.commands[2].arguments
    assert plan.commands[3].arguments[-1] == str(
        plan.source_root / "packaging" / "sector.spec"
    )
    assert "--workpath" in plan.commands[3].arguments
    assert "--distpath" in plan.commands[3].arguments
    assert "--clean" not in plan.commands[3].arguments
    for command in plan.commands:
        assert command.cwd == plan.source_root
        assert command.environment["SECTOR_SOURCE_REVISION"] == commit
        assert command.environment["PYTHONHASHSEED"] == "1"
        assert str(root) not in command.arguments


def test_build_environment_removes_inherited_code_and_git_controls(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "hostile")
    monkeypatch.setenv("git_config_global", "hostile")
    monkeypatch.setenv("PYTHONPATH", "hostile")
    monkeypatch.setenv("PYTHONHOME", "hostile")
    monkeypatch.setenv("PYTHONSTARTUP", "hostile")
    monkeypatch.setenv("PYTHONHASHSEED", "random")
    monkeypatch.setenv("SECTOR_SOURCE_REVISION", "wrong")
    monkeypatch.setenv("SECTOR_KEEP", "yes")

    environment = _build_environment(
        source_revision="a" * 40,
        source_tree="b" * 40,
        source_committer_epoch=123,
        source_committed_at_utc="1970-01-01T00:02:03+00:00",
        source_file_count=7,
        source_total_bytes=11,
        source_inventory_sha256="c" * 64,
    )

    assert all(not key.upper().startswith("GIT_") for key in environment)
    assert all(key.upper() not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}
               for key in environment)
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PYTHONHASHSEED"] == "1"
    assert environment["SECTOR_SOURCE_REVISION"] == "a" * 40
    assert environment["SECTOR_SOURCE_TREE"] == "b" * 40
    assert environment["SECTOR_SOURCE_COMMITTER_EPOCH"] == "123"
    assert environment["SOURCE_DATE_EPOCH"] == "123"
    assert environment["SECTOR_SOURCE_COMMITTED_AT_UTC"] == (
        "1970-01-01T00:02:03+00:00"
    )
    assert environment["SECTOR_SOURCE_FILE_COUNT"] == "7"
    assert environment["SECTOR_SOURCE_TOTAL_BYTES"] == "11"
    assert environment["SECTOR_SOURCE_INVENTORY_SHA256"] == "c" * 64
    assert environment["SECTOR_KEEP"] == "yes"


def test_prepare_writes_create_only_canonical_source_identity(tmp_path):
    root, commit, _accepted = _repository(tmp_path)
    plan = prepare_exact_build(root, commit, tmp_path / "build-run")

    identity = json.loads(plan.source_identity_path.read_text(encoding="ascii"))
    evidence = plan.source_evidence
    assert identity == {
        "source_revision": commit,
        "source_tree": evidence.source_tree,
        "source_committer_epoch": evidence.source_committer_epoch,
        "source_committed_at_utc": evidence.source_committed_at_utc,
        "source_file_count": evidence.file_count,
        "source_total_bytes": evidence.total_bytes,
        "source_inventory_sha256": evidence.inventory_sha256,
    }
    assert plan.source_identity_path == plan.run_root / "source-identity.json"
    assert plan.commands[3].environment["SOURCE_DATE_EPOCH"] == str(
        evidence.source_committer_epoch
    )


def test_execute_build_assembles_only_new_files_from_isolated_source(tmp_path):
    root, commit, _accepted = _repository(tmp_path)
    plan = prepare_exact_build(root, commit, tmp_path / "build-run")
    calls = []

    def runner(command):
        calls.append(command)
        if "generate_third_party_notices.py" in command.arguments[1]:
            notice = plan.source_root / "build" / "legal" / "THIRD_PARTY_NOTICES.txt"
            notice.parent.mkdir(parents=True)
            notice.write_bytes(b"accepted notices\n")
        if "PyInstaller" in command.arguments:
            plan.package_root.mkdir(parents=True)
            (plan.package_root / "Sector.exe").write_bytes(b"unsigned fixture")

    evidence = execute_exact_build(plan, runner=runner)

    assert calls == list(plan.commands)
    assert evidence.source_revision == commit
    assert evidence.package_root == plan.package_root
    assert (plan.package_root / "LICENSE.txt").read_bytes() == b"accepted-license\n"
    assert (plan.package_root / "THIRD_PARTY_NOTICES.txt").read_bytes() == (
        b"accepted notices\n"
    )


def test_execute_build_never_overwrites_an_unexpected_package_file(tmp_path):
    root, commit, _accepted = _repository(tmp_path)
    plan = prepare_exact_build(root, commit, tmp_path / "build-run")
    marker = b"preserve unexpected output\n"

    def runner(command):
        if "generate_third_party_notices.py" in command.arguments[1]:
            notice = plan.source_root / "build" / "legal" / "THIRD_PARTY_NOTICES.txt"
            notice.parent.mkdir(parents=True)
            notice.write_bytes(b"accepted notices\n")
        if "PyInstaller" in command.arguments:
            plan.package_root.mkdir(parents=True)
            (plan.package_root / "Sector.exe").write_bytes(b"unsigned fixture")
            (plan.package_root / "LICENSE.txt").write_bytes(marker)

    with pytest.raises(ExactBuildError, match="already exists"):
        execute_exact_build(plan, runner=runner)
    assert (plan.package_root / "LICENSE.txt").read_bytes() == marker


def test_existing_run_root_is_rejected_without_modification(tmp_path):
    root, commit, _accepted = _repository(tmp_path)
    output = tmp_path / "build-run"
    output.mkdir()
    marker = output / "preserve.txt"
    marker.write_text("preserve\n", encoding="ascii")

    with pytest.raises(ExactBuildError, match="already exists"):
        prepare_exact_build(root, commit, output)
    assert marker.read_text(encoding="ascii") == "preserve\n"


def test_tracked_generated_path_is_preserved_and_rejected(tmp_path):
    root, _commit, _accepted = _repository(tmp_path)
    generated = root / "build" / "sector_build_info.json"
    generated.parent.mkdir()
    generated.write_text('{"preserve": true}\n', encoding="ascii")
    _git(root, "add", "build/sector_build_info.json")
    _git(root, "commit", "--quiet", "-m", "unexpected generated path")
    commit = _git(root, "rev-parse", "HEAD")
    output = tmp_path / "build-run"

    with pytest.raises(ExactBuildError, match="generated exact-source path"):
        prepare_exact_build(root, commit, output)
    assert (output / "source" / "build" / "sector_build_info.json").read_text(
        encoding="ascii"
    ) == '{"preserve": true}\n'


def test_symlink_aware_run_root_check_precedes_resolution(tmp_path, monkeypatch):
    root, commit, _accepted = _repository(tmp_path)
    output = tmp_path / "build-run"
    original_lexists = os.path.lexists

    def reports_dangling_entry(path):
        if os.fspath(path) == os.fspath(output):
            return True
        return original_lexists(path)

    monkeypatch.setattr(os.path, "lexists", reports_dangling_entry)

    with pytest.raises(ExactBuildError, match="already exists"):
        prepare_exact_build(root, commit, output)


def test_powershell_and_qa_workflow_delegate_to_exact_build_driver():
    script = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "qa.yml").read_text(
        encoding="utf-8"
    )

    for text in (script, workflow):
        assert "tools/build_exact_commit.py" in text
        assert "--source-revision" in text
        assert "--output" in text
        assert "python -m PyInstaller" not in text
        assert "generate_third_party_notices.py --output" not in text
        assert "Copy-Item -LiteralPath LICENSE" not in text
    assert "SECTOR_EXACT_BUILD_ROOT" in workflow
    assert "dist/Sector" not in script
    assert "-Force" not in script


def test_driver_cli_isolated_help_has_no_third_party_dependency():
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "tools" / "build_exact_commit.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--source-revision" in result.stdout
    assert "--output" in result.stdout
