# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a standalone Sector build (ONEDIR).

Build from the repo root:  pyinstaller packaging/sector.spec
The result is dist/Sector/Sector.exe plus its _internal dependencies.
"""

import datetime
import json
import os
import re

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
WINDOWS_VERSION_INFO = os.path.join(SPECPATH, "windows_version_info.txt")

datas, binaries, hiddenimports = [], [], []


def _source_revision(root):
    """Read the checkout revision without depending on a Git executable."""
    revision = os.environ.get("SECTOR_SOURCE_REVISION") or os.environ.get("GITHUB_SHA")
    if revision:
        return revision.strip()
    git_dir = os.path.join(root, ".git")
    try:
        if os.path.isfile(git_dir):
            with open(git_dir, encoding="ascii") as stream:
                marker = stream.read().strip()
            if marker.lower().startswith("gitdir:"):
                git_dir = marker.split(":", 1)[1].strip()
                if not os.path.isabs(git_dir):
                    git_dir = os.path.abspath(os.path.join(root, git_dir))
        with open(os.path.join(git_dir, "HEAD"), encoding="ascii") as stream:
            head = stream.read().strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(":", 1)[1].strip()
        loose = os.path.join(git_dir, *ref.split("/"))
        if os.path.isfile(loose):
            with open(loose, encoding="ascii") as stream:
                return stream.read().strip()
        packed = os.path.join(git_dir, "packed-refs")
        if os.path.isfile(packed):
            with open(packed, encoding="ascii") as stream:
                for line in stream:
                    if line.rstrip().endswith(" " + ref):
                        return line.split(" ", 1)[0]
    except OSError:
        pass
    return "unavailable"


def _sector_metadata(root):
    with open(os.path.join(root, "sector", "__init__.py"), encoding="utf-8") as stream:
        source = stream.read()
    metadata = {}
    for key in (
        "__version__",
        "__product_name__",
        "__description__",
        "__author__",
        "__licensee__",
    ):
        match = re.search(
            rf'^{re.escape(key)}\s*=\s*"([^"]+)"', source, re.MULTILINE
        )
        if match is None:
            raise ValueError(f"Sector product identity is missing {key}")
        metadata[key] = match.group(1)
    copyright_match = re.search(
        r'__copyright__\s*=\s*\(\s*"([^"]+)"\s*\)', source, re.MULTILINE
    )
    if copyright_match is None:
        raise ValueError("Sector product identity is missing __copyright__")
    metadata["__copyright__"] = copyright_match.group(1)
    return metadata


# Embed the exact source state in the packaged runtime. The generated manifest
# lives under ignored build output and is added beside sector/build_info.py.
manifest_path = os.path.join(ROOT, "build", "sector_build_info.json")
os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
metadata = _sector_metadata(ROOT)
with open(manifest_path, "w", encoding="utf-8") as stream:
    json.dump({
        "product_name": metadata["__product_name__"],
        "description": metadata["__description__"],
        "sector_version": metadata["__version__"],
        "source_revision": _source_revision(ROOT),
        "author": metadata["__author__"],
        "licensee": metadata["__licensee__"],
        "copyright": metadata["__copyright__"],
        "built_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        ),
    }, stream, indent=2)
datas += [(manifest_path, "sector")]


def _kaleido_runtime_module(name):
    """Exclude Kaleido's CLI mocker, which parses PyInstaller's own arguments."""
    return not name.startswith("kaleido.mocker")


# Heavy third-party packages: pull in their data files, binaries and submodules
# (Streamlit ships its compiled frontend as data; numba/llvmlite ship binaries).
for pkg in ("streamlit", "plotly", "numba", "llvmlite", "kaleido",
            "reportlab", "pypdf", "pandas", "pyarrow", "altair"):
    options = ({"filter_submodules": _kaleido_runtime_module}
               if pkg == "kaleido" else {})
    d, b, h = collect_all(pkg, **options)
    datas += d
    binaries += b
    hiddenimports += h

# Streamlit (and a few deps) read their version via importlib.metadata at runtime.
for pkg in ("streamlit", "numpy", "plotly", "pandas", "pyarrow", "altair", "kaleido"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# Sector's own code: Streamlit executes app/sector_app.py as a file and the app
# adds its folder and the repo root to sys.path, so ship both trees as data with
# their structure preserved (sources, the vendored point-grid frontend, fonts).
# The sidebar logo lives in the repo-root ``assets`` folder (loaded relative to the
# repo root / bundle base), so ship that too or the packaged UI drops the logo.
datas += [(os.path.join(ROOT, "app"), "app"),
          (os.path.join(ROOT, "sector"), "sector"),
          (os.path.join(ROOT, "assets"), "assets")]

hiddenimports += [
    "sector",
    "streamlit.runtime.scriptrunner.magic_funcs",
    "streamlit.web.cli",
]

a = Analysis(
    [os.path.join(SPECPATH, "run_sector.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PyInstaller"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Sector",
    version=WINDOWS_VERSION_INFO,
    console=True,                 # keep a console so the local URL / errors are visible
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Sector",
)
