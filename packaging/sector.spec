# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a standalone Sector build (ONEDIR).

Build from the repo root:  pyinstaller packaging/sector.spec
The result is dist/Sector/Sector.exe plus its _internal dependencies.
"""

import ast
import json
import os

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
WINDOWS_VERSION_INFO = os.path.join(SPECPATH, "windows_version_info.txt")

datas, binaries, hiddenimports = [], [], []

# Uvicorn selects these modules from string registries while Streamlit starts
# its ASGI server, so PyInstaller cannot discover them from normal imports. Keep
# this list scoped to the locked Windows runtime instead of collecting all of
# Uvicorn (including reload, worker and optional protocol implementations).
UVICORN_RUNTIME_HIDDEN_IMPORTS = (
    "uvicorn.lifespan.on",
    "uvicorn.loops.asyncio",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.websockets_sansio_impl",
)

# AnyIO resolves the active async backend through importlib while Starlette runs
# Streamlit's lifespan inside Uvicorn's asyncio event loop. PyInstaller cannot
# see that formatted module name. The packaged server never selects AnyIO's
# optional Trio backend, so retain only the locked runtime route instead of
# collecting every AnyIO backend.
ANYIO_RUNTIME_HIDDEN_IMPORTS = (
    "anyio._backends._asyncio",
)


def _sector_metadata(root):
    """Read complete package identity from Sector's source-of-truth module."""
    path = os.path.join(root, "sector", "__init__.py")
    with open(path, encoding="utf-8") as stream:
        tree = ast.parse(stream.read(), filename=path)
    required = {
        "__version__",
        "__product_name__",
        "__description__",
        "__author__",
        "__licensee__",
        "__copyright__",
    }
    metadata = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in required:
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Sector product identity is invalid: {target.id}")
        metadata[target.id] = value
    missing = sorted(required.difference(metadata))
    if missing:
        raise ValueError(f"Sector product identity is missing: {', '.join(missing)}")
    return metadata


# Embed small, useful runtime metadata for support diagnostics.
manifest_path = os.path.join(ROOT, "build", "sector_build_info.json")
os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
metadata = _sector_metadata(ROOT)
source_revision = str(os.environ.get("SECTOR_SOURCE_REVISION", "unavailable")).strip()
if not source_revision:
    source_revision = "unavailable"
manifest = {
    "product_name": metadata["__product_name__"],
    "description": metadata["__description__"],
    "sector_version": metadata["__version__"],
    "author": metadata["__author__"],
    "licensee": metadata["__licensee__"],
    "copyright": metadata["__copyright__"],
    "source_revision": source_revision,
}
with open(manifest_path, "wb") as stream:
    stream.write(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("ascii")
    )
datas += [(manifest_path, "sector")]


def _runtime_module(name):
    """Exclude developer-only tests, benchmarks and optional plotting adapters."""
    parts = set(name.casefold().split("."))
    if parts.intersection({"test", "tests", "benchmark", "benchmarks", "conftest"}):
        return False
    return not (
        name.startswith("kaleido.mocker")
        or name.startswith("plotly.matplotlylib")
    )


def _runtime_package_data(entries):
    """Keep runtime assets, not duplicate sources or developer-only payloads."""
    retained = []
    source_suffixes = {".c", ".cpp", ".h", ".hpp", ".pxd", ".py", ".pyi", ".pyx"}
    developer_parts = {
        ".agents",
        "benchmark",
        "benchmarks",
        "conftest",
        "include",
        "labextension",
        "samples",
        "test",
        "tests",
        "testing",
    }
    for source, destination in entries:
        normalized = str(destination).replace("\\", "/").casefold()
        parts = set(normalized.split("/"))
        if parts.intersection(developer_parts):
            continue
        if os.path.splitext(str(source))[1].casefold() in source_suffixes:
            continue
        retained.append((source, destination))
    return retained


def _without_installer_records(entries):
    """Omit pip RECORD inventories whose external launcher hashes are path-bound."""
    retained = []
    for entry in entries:
        destination = str(entry[0]).replace("\\", "/")
        parts = destination.split("/")
        if (
            len(parts) >= 2
            and parts[-1].casefold() == "record"
            and parts[-2].casefold().endswith(".dist-info")
        ):
            continue
        retained.append(entry)
    return retained


def _without_pyarrow_developer_payload(entries):
    """Omit PyArrow build sources and tests while retaining runtime binaries."""
    retained = []
    source_suffixes = {
        ".c", ".cc", ".cpp", ".h", ".hpp", ".pxd", ".pxi", ".pyx"
    }
    developer_parts = {"include", "includes", "src", "test", "tests", "testing"}
    for entry in entries:
        destination = str(entry[0]).replace("\\", "/")
        parts = set(destination.casefold().split("/"))
        is_pyarrow = "pyarrow" in parts
        suffix = os.path.splitext(destination)[1].casefold()
        if is_pyarrow and (
            parts.intersection(developer_parts) or suffix in source_suffixes
        ):
            continue
        retained.append(entry)
    return retained


# Heavy third-party packages: pull in their data files, binaries and submodules
# (Streamlit ships its compiled frontend as data; numba/llvmlite ship binaries).
for pkg in ("streamlit", "plotly", "numba", "llvmlite", "kaleido",
            "reportlab", "pandas", "pyarrow", "altair"):
    d, b, h = collect_all(pkg, filter_submodules=_runtime_module)
    datas += _runtime_package_data(d)
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
hiddenimports += UVICORN_RUNTIME_HIDDEN_IMPORTS
hiddenimports += ANYIO_RUNTIME_HIDDEN_IMPORTS

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
# Hook-provided distribution metadata can include pip's RECORD inventory. On
# Windows it hashes generated ../Scripts/*.exe launchers whose bytes embed the
# unique virtual-environment path; those launchers are not part of the frozen
# package. Retain runtime metadata, licences and entry points, but omit only the
# installer inventory after every hook has expanded its data inputs.
a.datas = _without_pyarrow_developer_payload(a.datas)
a.datas = _without_installer_records(a.datas)

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
