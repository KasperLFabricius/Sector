# Inspecting an unsigned Sector Windows QA build

The ordinary build scripts and the `Sector QA` workflow produce an **unsigned,
non-distributable QA artifact** for static package inspection. Do not launch,
zip or distribute this artifact. A distributable Sector package requires the
separately authorised signing workflow; there is no unsigned fallback.

## Build

The easiest inspection build is to **double-click `packaging/build.bat`**. It
wraps the PowerShell build with an execution-policy bypass (so it works even
when running `.ps1` files is blocked) and keeps the window open to show the
result and the unsigned-artifact warning.

Equivalently, from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build.ps1
```

The script requires a clean tracked source tree and rejects untracked files
inside the packaged `app`, `sector`, or `assets` trees. It derives the exact
source revision and `SOURCE_DATE_EPOCH` from the checked-out commit, then builds
two clean package trees with separate work directories. PyInstaller's generated
stored standard-library ZIP is canonicalized by validated member name and order;
member payloads are not filtered or changed. Both packages then pass the complete
source/product/legal verifier and an independent path/size/SHA-256 comparison.

Every run uses a new directory under the repository's ignored
`build/unsigned-package-*` tree; previous QA artifacts are not overwritten and
the generated packages cannot be staged accidentally. The `primary/Sector/`
subtree is the inspection package and `package-reproducibility.json` records the
controlled unsigned tree hash. Keep both packages local and use them only for
static QA inspection. Do not execute either unsigned `Sector.exe`.

The reproducibility claim applies to the complete unsigned package built twice
from the same locked environment, source revision and commit epoch. Genuine
Authenticode/RFC3161 signing changes the executable, so Sector does not claim
that independently signed package bytes are identical.

## Signed-package runtime design

After a package has passed the separately authorised signing gate, `Sector.exe`
launches the Streamlit app exactly as `streamlit run app/sector_app.py` does
(`packaging/run_sector.py` is the entry point) and opens the browser at the local
URL. A console window stays open to show that URL and any messages.

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
| `build.ps1` | Controlled QA build: derives source identity, builds twice, verifies both trees and writes SHA-256 comparison evidence. |
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
