"""Checked, self-contained raster illustrations for the offline HTML manual."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

ASSET_ROOT = Path(__file__).resolve().parent.parent / "assets" / "manual"


def figure_data_uri(factory) -> str:
    """Embed one inventoried image and reject missing or damaged assets."""
    name = factory.__name__
    manifest = json.loads((ASSET_ROOT / "manifest.json").read_text(encoding="ascii"))
    record = manifest["figures"][name]
    payload = (ASSET_ROOT / (name + ".png")).read_bytes()
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"Manual image is not PNG: {name}")
    if hashlib.sha256(payload).hexdigest() != record["png_sha256"]:
        raise ValueError(f"Manual image checksum differs: {name}")
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")
