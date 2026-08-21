"""Focused contract for the built executable's private image-worker smoke."""

from __future__ import annotations

import os

import pytest

from tools import verify_portable_image_export as smoke


def test_packaged_worker_route_warms_and_returns_a_real_png_contract(
    tmp_path,
    monkeypatch,
) -> None:
    package = tmp_path / "Sector-portable"
    package.mkdir()
    executable = package / "Sector.exe"
    executable.write_bytes(b"MZ")
    workspace = tmp_path / "image-smoke"
    launches = []
    exports = []
    closed = []

    def launch(command, *, stderr):
        assert stderr is not None
        launches.append(command)
        return object(), object()

    class Coordinator:
        def __init__(self, *, worker_launcher, register_exit) -> None:
            self.worker_launcher = worker_launcher
            register_exit(lambda: None)

        def export_png(self, figure, **options):
            self.worker_launcher()
            exports.append((figure, options, os.environ["SECTOR_KALEIDO_DIR"]))
            return smoke.image_export._PNG_SIGNATURE + b"packaged"

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(smoke.image_export, "_launch_worker_command", launch)
    monkeypatch.setattr(smoke.image_export, "KaleidoExportCoordinator", Coordinator)
    monkeypatch.setenv("SECTOR_KALEIDO_DIR", "retained-value")

    evidence = smoke.run_portable_image_export_smoke(
        package,
        workspace,
        timeout_seconds=17.0,
    )

    assert launches == [
        [str(executable), smoke.image_export._FROZEN_WORKER_FLAG]
    ]
    assert len(exports) == 1
    assert exports[0][1] == {
        "width": 96,
        "height": 96,
        "scale": 1,
        "timeout": 17.0,
        "description": "packaged publication image smoke",
    }
    assert exports[0][2] == str(workspace.resolve())
    assert closed == [True]
    assert evidence.executable == str(executable)
    assert evidence.png_bytes > len(smoke.image_export._PNG_SIGNATURE)
    assert os.environ["SECTOR_KALEIDO_DIR"] == "retained-value"


def test_packaged_worker_smoke_fails_closed_without_exact_executable(tmp_path) -> None:
    with pytest.raises(smoke.PortableImageExportError, match="Sector.exe"):
        smoke.run_portable_image_export_smoke(
            tmp_path,
            tmp_path / "workspace",
        )
    assert not (tmp_path / "workspace").exists()


def test_packaged_worker_failure_restores_environment_and_closes(
    tmp_path,
    monkeypatch,
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "Sector.exe").write_bytes(b"MZ")
    closed = []

    class Coordinator:
        def __init__(self, **_kwargs) -> None:
            pass

        def export_png(self, *_args, **_kwargs):
            raise smoke.image_export.KaleidoExportError("unavailable")

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(smoke.image_export, "KaleidoExportCoordinator", Coordinator)
    monkeypatch.delenv("SECTOR_KALEIDO_DIR", raising=False)

    with pytest.raises(smoke.PortableImageExportError, match="unavailable"):
        smoke.run_portable_image_export_smoke(
            package,
            tmp_path / "workspace",
        )

    assert closed == [True]
    assert "SECTOR_KALEIDO_DIR" not in os.environ
