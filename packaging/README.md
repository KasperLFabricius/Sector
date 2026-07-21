# Packaging Sector as a standalone Windows app

This builds a self-contained Sector that colleagues can run **without installing
Python** -- a folder with `Sector.exe` and its bundled dependencies (PyInstaller
ONEDIR).

## Build

The easiest way is to **double-click `packaging/build.bat`**. It wraps the
PowerShell build with an execution-policy bypass (so it works even when running
`.ps1` files is blocked) and keeps the window open to show the result.

Equivalently, from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build.ps1
```

or directly:

```powershell
python -m pip install --require-hashes -r requirements-build.txt
python tools/generate_third_party_notices.py --output build/legal/THIRD_PARTY_NOTICES.txt
python -m PyInstaller --noconfirm --clean packaging/sector.spec
Copy-Item LICENSE dist/Sector/LICENSE.txt
Copy-Item build/legal/THIRD_PARTY_NOTICES.txt dist/Sector/THIRD_PARTY_NOTICES.txt
```

The result is `dist/Sector/`, including Sector's proprietary notice and the
generated third-party notice bundle. Zip that whole folder to distribute it;
the user unzips it anywhere and runs `Sector.exe`.

## What it does

`Sector.exe` launches the Streamlit app exactly as `streamlit run app/sector_app.py`
does (`packaging/run_sector.py` is the entry point) and opens the browser at the
local URL. A console window stays open to show that URL and any messages.

Sector serves only on this computer at **127.0.0.1:8502**
(`http://127.0.0.1:8502`) instead of Streamlit's default 8501, so it can run
alongside BriCoS (which uses 8501) without a clash. Set the `SECTOR_PORT`
environment variable to use a different port.

The packaged launcher disables usage telemetry. The application toolbar keeps
viewer actions such as print and theme selection, but hides Streamlit's deploy,
rerun, and clear-cache developer actions. Browser errors show the exception type
without exposing local paths or tracebacks; full diagnostics remain available in
the console for support.

## Files

| File | Purpose |
|---|---|
| `run_sector.py` | Frozen entry point: resolves the bundled app path and starts Streamlit. |
| `sector.spec` | PyInstaller spec: collects Streamlit/Plotly/numba/kaleido/reportlab and bundles the `app` and `sector` trees (including the vendored point-grid frontend). |
| `build.ps1` | Convenience build script: installs the lock, generates notices, builds and assembles the package. |
| `build.bat` | Double-click wrapper around `build.ps1` (execution-policy bypass). |

## Runtime notes

- **Writable state.** The autosave file and numba's compile cache go to
  `%LOCALAPPDATA%\Sector` (set via `SECTOR_AUTOSAVE_DIR` / `NUMBA_CACHE_DIR` in the
  launcher), so a read-only install location (e.g. Program Files) does not break
  startup.
- **Report figures need a browser engine.** The PDF report exports its plots with
  kaleido, which needs Chrome/Chromium at runtime. If a requested figure cannot be
  embedded, report generation fails visibly instead of issuing an incomplete PDF.
- **numba** speeds up the plastic solver but is optional -- if it cannot load in the
  frozen build the app falls back to the (slower) pure-Python kernels.
