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


def _commit_revision(value):
    """Return a complete Git commit identity, never a label or abbreviation."""
    candidate = str(value or "").strip()
    hexadecimal = "0123456789abcdefABCDEF"
    if len(candidate) != 40 or any(char not in hexadecimal for char in candidate):
        return None
    return candidate


def _git_directories(root):
    """Return the worktree and shared Git metadata directories."""
    control = os.path.join(root, ".git")
    if os.path.isdir(control):
        git_dir = control
    else:
        with open(control, encoding="ascii") as stream:
            marker = stream.read().strip()
        prefix, separator, location = marker.partition(":")
        if separator != ":" or prefix.casefold() != "gitdir" or not location.strip():
            raise ValueError("invalid .git control file")
        git_dir = location.strip()
        if not os.path.isabs(git_dir):
            git_dir = os.path.abspath(os.path.join(root, git_dir))

    common_dir = git_dir
    common_marker = os.path.join(git_dir, "commondir")
    if os.path.isfile(common_marker):
        with open(common_marker, encoding="ascii") as stream:
            common_dir = stream.read().strip()
        if not common_dir:
            raise ValueError("empty Git commondir")
        if not os.path.isabs(common_dir):
            common_dir = os.path.abspath(os.path.join(git_dir, common_dir))
    return git_dir, common_dir


def _source_revision(root):
    """Resolve an exact commit from the environment or checkout metadata."""
    for variable in ("SECTOR_SOURCE_REVISION", "GITHUB_SHA"):
        revision = _commit_revision(os.environ.get(variable))
        if revision is not None:
            return revision

    try:
        git_dir, common_dir = _git_directories(root)
        with open(os.path.join(git_dir, "HEAD"), encoding="ascii") as stream:
            head = stream.read().strip()
        if not head.startswith("ref:"):
            revision = _commit_revision(head)
            if revision is not None:
                return revision
        else:
            ref = head.partition(":")[2].strip()
            if not ref:
                raise ValueError("empty symbolic HEAD")
            ref_roots = [git_dir]
            if common_dir != git_dir:
                ref_roots.append(common_dir)
            for ref_root in ref_roots:
                loose = os.path.join(ref_root, *ref.split("/"))
                if os.path.isfile(loose):
                    with open(loose, encoding="ascii") as stream:
                        revision = _commit_revision(stream.read())
                    if revision is not None:
                        return revision
            for ref_root in ref_roots:
                packed = os.path.join(ref_root, "packed-refs")
                if not os.path.isfile(packed):
                    continue
                with open(packed, encoding="ascii") as stream:
                    for line in stream:
                        revision_text, separator, packed_ref = line.strip().partition(" ")
                        if separator and packed_ref == ref:
                            revision = _commit_revision(revision_text)
                            if revision is not None:
                                return revision
    except (OSError, ValueError):
        pass
    raise ValueError(
        "Sector package source revision is unavailable; set "
        "SECTOR_SOURCE_REVISION to the exact 40-hex commit"
    )


def _source_date_epoch():
    """Return the controlled source commit epoch used by the whole build."""
    candidate = str(os.environ.get("SOURCE_DATE_EPOCH") or "").strip()
    if (
        not candidate
        or not candidate.isascii()
        or not candidate.isdecimal()
        or (len(candidate) > 1 and candidate.startswith("0"))
    ):
        raise ValueError(
            "Sector package source date epoch is unavailable; set "
            "SOURCE_DATE_EPOCH to the non-negative integer commit timestamp"
        )
    epoch = int(candidate)
    try:
        datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("Sector package source date epoch is outside UTC range") from exc
    return epoch


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
source_revision = _source_revision(ROOT)
source_date_epoch = _source_date_epoch()
with open(manifest_path, "w", encoding="utf-8") as stream:
    json.dump({
        "product_name": metadata["__product_name__"],
        "description": metadata["__description__"],
        "sector_version": metadata["__version__"],
        "source_revision": source_revision,
        "source_date_epoch": source_date_epoch,
        "author": metadata["__author__"],
        "licensee": metadata["__licensee__"],
        "copyright": metadata["__copyright__"],
        "built_at_utc": datetime.datetime.fromtimestamp(
            source_date_epoch, tz=datetime.timezone.utc
        ).isoformat(
            timespec="seconds"
        ),
    }, stream, indent=2)
    stream.write("\n")
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
