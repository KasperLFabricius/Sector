"""Render one PNG through the private worker in a built Sector executable."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import publication_image_export as image_export  # noqa: E402


class PortableImageExportError(RuntimeError):
    """The packaged publication image worker did not render correctly."""


@dataclass(frozen=True)
class PortableImageExportEvidence:
    executable: str
    png_bytes: int


def run_portable_image_export_smoke(
    package: Path,
    workspace: Path,
    *,
    timeout_seconds: float = 120.0,
) -> PortableImageExportEvidence:
    """Launch the frozen private route, warm Kaleido, and render one real PNG."""

    folder = Path(os.path.abspath(package))
    executable = folder / "Sector.exe"
    selected_workspace = Path(os.path.abspath(workspace))
    if not folder.is_dir() or not executable.is_file():
        raise PortableImageExportError(
            "package must be a folder containing Sector.exe"
        )
    if os.path.lexists(selected_workspace):
        raise PortableImageExportError(
            f"image-export workspace already exists: {selected_workspace}"
        )
    try:
        selected_workspace.mkdir(parents=True)
    except OSError as exc:
        raise PortableImageExportError(
            "cannot create image-export workspace"
        ) from exc

    previous_kaleido_dir = os.environ.get("SECTOR_KALEIDO_DIR")
    os.environ["SECTOR_KALEIDO_DIR"] = str(selected_workspace)
    coordinator: image_export.KaleidoExportCoordinator | None = None
    stderr_log = None
    try:
        stderr_log = (selected_workspace / "worker-stderr.log").open("xb")
        coordinator = image_export.KaleidoExportCoordinator(
            worker_launcher=lambda: image_export._launch_worker_command(
                [str(executable), image_export._FROZEN_WORKER_FLAG],
                stderr=stderr_log,
            ),
            register_exit=lambda _callback: None,
        )
        payload = coordinator.export_png(
            {
                "data": [
                    {
                        "type": "scatter",
                        "x": [0.0, 1.0],
                        "y": [0.0, 1.0],
                        "mode": "lines+markers",
                    }
                ]
            },
            width=96,
            height=96,
            scale=1,
            timeout=timeout_seconds,
            description="packaged publication image smoke",
        )
    except (image_export.KaleidoExportError, OSError, ValueError) as exc:
        raise PortableImageExportError(
            f"packaged publication image export failed: {exc}"
        ) from exc
    finally:
        if coordinator is not None:
            coordinator.close()
        if stderr_log is not None:
            stderr_log.close()
        if previous_kaleido_dir is None:
            os.environ.pop("SECTOR_KALEIDO_DIR", None)
        else:
            os.environ["SECTOR_KALEIDO_DIR"] = previous_kaleido_dir

    if not payload.startswith(image_export._PNG_SIGNATURE):
        raise PortableImageExportError(
            "packaged publication image worker returned no PNG"
        )
    return PortableImageExportEvidence(
        executable=str(executable),
        png_bytes=len(payload),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        evidence = run_portable_image_export_smoke(
            arguments.package,
            arguments.workspace,
            timeout_seconds=arguments.timeout_seconds,
        )
    except PortableImageExportError as exc:
        print(f"Portable image-export smoke failed: {exc}", file=sys.stderr)
        return 2
    print(
        "Portable image-export smoke passed: "
        f"the frozen worker returned {evidence.png_bytes} PNG bytes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
