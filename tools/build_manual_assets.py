"""Regenerate checked offline-manual images from their native figure factories."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "app"), str(ROOT)]

import manual
from manual_assets import ASSET_ROOT


def build():
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    records = {}
    for block in manual.manual_blocks():
        if block[0] != "figure":
            continue
        factory = block[1]
        name = factory.__name__
        if name in records:
            continue
        figure = factory()
        source = figure.to_json().encode("utf-8")
        payload = manual._fig_to_png(factory)
        (ASSET_ROOT / (name + ".png")).write_bytes(payload)
        records[name] = {
            "figure_sha256": hashlib.sha256(source).hexdigest(),
            "png_sha256": hashlib.sha256(payload).hexdigest(),
        }
        print(name, len(payload), flush=True)
    (ASSET_ROOT / "manifest.json").write_text(
        json.dumps({"version": manual.APP_VERSION, "figures": records}, indent=2)
        + "\n",
        encoding="ascii",
    )


if __name__ == "__main__":
    build()
