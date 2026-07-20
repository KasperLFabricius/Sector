"""Runtime build provenance for source checkouts and packaged Sector builds."""

from __future__ import annotations

import json
import os
from pathlib import Path

_MANIFEST = "sector_build_info.json"


def _git_dir(root: Path) -> Path | None:
    """Resolve a normal checkout or Git worktree metadata directory."""
    marker = root / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():
        try:
            line = marker.read_text(encoding="ascii").strip()
        except OSError:
            return None
        if line.lower().startswith("gitdir:"):
            path = Path(line.split(":", 1)[1].strip())
            return path if path.is_absolute() else (root / path).resolve()
    return None


def _git_revision(root: Path) -> str | None:
    """Read a Git revision without launching Git or another executable."""
    git_dir = _git_dir(root)
    if git_dir is None:
        return None
    try:
        head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
        if not head.startswith("ref:"):
            return head or None
        ref = head.split(":", 1)[1].strip()
        loose = git_dir / Path(ref)
        if loose.is_file():
            return loose.read_text(encoding="ascii").strip() or None
        packed = git_dir / "packed-refs"
        if packed.is_file():
            suffix = " " + ref
            for line in packed.read_text(encoding="ascii").splitlines():
                if line and not line.startswith(("#", "^")) and line.endswith(suffix):
                    return line.split(" ", 1)[0]
    except OSError:
        return None
    return None


def _packaged_manifest() -> dict:
    path = Path(__file__).resolve().with_name(_MANIFEST)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def source_revision() -> str:
    """Return the exact build/source revision where available."""
    env = str(os.environ.get("SECTOR_SOURCE_REVISION", "")).strip()
    if env:
        return env
    manifest = _packaged_manifest()
    recorded = str(manifest.get("source_revision", "")).strip()
    if recorded:
        return recorded
    revision = _git_revision(Path(__file__).resolve().parent.parent)
    return revision or "unavailable"


def short_revision(revision: str | None = None) -> str:
    value = str(source_revision() if revision is None else revision).strip()
    return value[:12] if value and value != "unavailable" else "unavailable"
