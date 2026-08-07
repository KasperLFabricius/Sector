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


def _required_environment(name):
    value = os.environ.get(name)
    if value is None or not value or value != value.strip():
        raise ValueError(f"Sector package identity is missing or ambiguous: {name}")
    return value


def _exact_lower_hex(name, length):
    value = _required_environment(name)
    if len(value) != length or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"Sector package identity is invalid: {name}")
    return value


def _canonical_integer(name, minimum):
    value = _required_environment(name)
    if not value.isascii() or not value.isdecimal():
        raise ValueError(f"Sector package identity is invalid: {name}")
    number = int(value)
    if number < minimum or str(number) != value:
        raise ValueError(f"Sector package identity is noncanonical: {name}")
    return number


def _source_identity():
    schema = _required_environment("SECTOR_SOURCE_IDENTITY_SCHEMA")
    if schema != "sector-source-identity-v1":
        raise ValueError("Sector package source-identity schema is unsupported")
    revision = _exact_lower_hex("SECTOR_SOURCE_REVISION", 40)
    source_tree = _exact_lower_hex("SECTOR_SOURCE_TREE", 40)
    source_epoch = _canonical_integer("SECTOR_SOURCE_EPOCH", 0)
    source_date_epoch = _canonical_integer("SOURCE_DATE_EPOCH", 0)
    if source_date_epoch != source_epoch:
        raise ValueError("SOURCE_DATE_EPOCH differs from the sealed source epoch")
    source_file_count = _canonical_integer("SECTOR_SOURCE_FILE_COUNT", 1)
    source_total_bytes = _canonical_integer("SECTOR_SOURCE_TOTAL_BYTES", 0)
    inventory = _exact_lower_hex("SECTOR_SOURCE_INVENTORY_SHA256", 64)
    try:
        built_at_utc = datetime.datetime.fromtimestamp(
            source_epoch, datetime.timezone.utc
        ).isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError) as exc:
        raise ValueError("Sector package source epoch is outside the UTC range") from exc
    return {
        "schema": schema,
        "source_revision": revision,
        "source_tree": source_tree,
        "source_epoch": source_epoch,
        "built_at_utc": built_at_utc,
        "source_file_count": source_file_count,
        "source_total_bytes": source_total_bytes,
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
source_identity = _source_identity()
with open(manifest_path, "x", encoding="utf-8") as stream:
    json.dump({
        "product_name": metadata["__product_name__"],
        "description": metadata["__description__"],
        "sector_version": metadata["__version__"],
        "author": metadata["__author__"],
        "licensee": metadata["__licensee__"],
        "copyright": metadata["__copyright__"],
        **source_identity,
    }, stream, indent=2, sort_keys=True)
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
