# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a standalone Sector build (ONEDIR).

Build from the repo root:  pyinstaller packaging/sector.spec
The result is dist/Sector/Sector.exe plus its _internal dependencies.
"""

import os

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas, binaries, hiddenimports = [], [], []

# Heavy third-party packages: pull in their data files, binaries and submodules
# (Streamlit ships its compiled frontend as data; numba/llvmlite ship binaries).
for pkg in ("streamlit", "plotly", "numba", "llvmlite", "kaleido",
            "reportlab", "pypdf", "pandas", "pyarrow", "altair"):
    d, b, h = collect_all(pkg)
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
    console=True,                 # keep a console so the local URL / errors are visible
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Sector",
)
