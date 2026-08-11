# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a standalone Sector build (ONEDIR).

Build from the repo root:  pyinstaller packaging/sector.spec
The result is dist/Sector/Sector.exe plus its _internal dependencies.
"""

import ast
import datetime
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


def _commit_revision(value):
    """Return one canonical lowercase SHA-1 identity."""
    candidate = str(value or "").strip()
    hexadecimal = "0123456789abcdef"
    if len(candidate) != 40 or any(char not in hexadecimal for char in candidate):
        raise ValueError("invalid sealed source commit identity")
    return candidate


def _canonical_integer(variable):
    value = str(os.environ.get(variable, ""))
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError(f"invalid sealed source integer: {variable}")
    if len(value) > 1 and value.startswith("0"):
        raise ValueError(f"noncanonical sealed source integer: {variable}")
    return int(value)


def _source_seal():
    revision = _commit_revision(os.environ.get("SECTOR_SOURCE_REVISION"))
    tree = _commit_revision(os.environ.get("SECTOR_SOURCE_TREE"))
    epoch = _canonical_integer("SECTOR_SOURCE_COMMITTER_EPOCH")
    if str(os.environ.get("SOURCE_DATE_EPOCH", "")) != str(epoch):
        raise ValueError("SOURCE_DATE_EPOCH does not match the sealed commit epoch")
    committed_at = str(os.environ.get("SECTOR_SOURCE_COMMITTED_AT_UTC", ""))
    canonical_time = datetime.datetime.fromtimestamp(
        epoch, tz=datetime.timezone.utc
    ).isoformat(timespec="seconds")
    if committed_at != canonical_time:
        raise ValueError("sealed source UTC time does not match the commit epoch")
    inventory = str(os.environ.get("SECTOR_SOURCE_INVENTORY_SHA256", ""))
    if len(inventory) != 64 or any(char not in "0123456789abcdef" for char in inventory):
        raise ValueError("invalid sealed source inventory digest")
    return {
        "source_revision": revision,
        "source_tree": tree,
        "source_committer_epoch": epoch,
        "source_committed_at_utc": committed_at,
        "source_file_count": _canonical_integer("SECTOR_SOURCE_FILE_COUNT"),
        "source_total_bytes": _canonical_integer("SECTOR_SOURCE_TOTAL_BYTES"),
        "source_inventory_sha256": inventory,
    }


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


# Embed the exact source state in the packaged runtime. The generated manifest
# lives under ignored build output and is added beside sector/build_info.py.
manifest_path = os.path.join(ROOT, "build", "sector_build_info.json")
os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
metadata = _sector_metadata(ROOT)
source_seal = _source_seal()
manifest = {
    "product_name": metadata["__product_name__"],
    "description": metadata["__description__"],
    "sector_version": metadata["__version__"],
    "author": metadata["__author__"],
    "licensee": metadata["__licensee__"],
    "copyright": metadata["__copyright__"],
    "built_at_utc": source_seal["source_committed_at_utc"],
    **source_seal,
}
with open(manifest_path, "xb") as stream:
    stream.write(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("ascii")
    )
datas += [(manifest_path, "sector")]


def _kaleido_runtime_module(name):
    """Exclude Kaleido's CLI mocker, which parses PyInstaller's own arguments."""
    return not name.startswith("kaleido.mocker")


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
hiddenimports += UVICORN_RUNTIME_HIDDEN_IMPORTS

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
