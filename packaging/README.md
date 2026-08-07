# Inspecting an unsigned Sector Windows QA build

The ordinary build scripts and the `Sector QA` workflow produce an **unsigned,
non-distributable QA artifact** for static package inspection. Each run first
exports one exact commit into a new isolated directory; dependency installation,
notice generation, PyInstaller analysis, and package assembly then read only
from that exported tree. Mutable worktree files are never packaging inputs.
The run also preserves a canonical `source-identity.json` seal whose commit,
tree, committer epoch, UTC time, file/byte counts, and raw inventory digest are
derived directly from authenticated Git objects. Package time is the commit
epoch; the spec has no checkout, `GITHUB_SHA`, or wall-clock fallback.
Do not launch, zip or distribute this artifact. A distributable Sector package
requires the separately authorised signing workflow; there is no unsigned
fallback.

## Build

The easiest inspection build is to **double-click `packaging/build.bat`**. It
resolves the exact current commit, creates a uniquely named run root under
`qa-artifacts/`, wraps the PowerShell build with an execution-policy bypass, and
keeps the window open to show the preserved output path and unsigned warning.

Equivalently, from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build.ps1
```

To select the identity and new output path explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build.ps1 `
  -SourceRevision <exact-lowercase-40-hex> `
  -OutputDirectory <new-nonexistent-path>
```

The inspection result is `<run-root>/dist/Sector/`, including Sector's
proprietary notice and generated third-party notice bundle. The same run root
preserves the exact exported source and PyInstaller work evidence. A path is
never reused, deleted, or overwritten. Keep the result local and use it only
for static QA inspection. Do not execute `Sector.exe` from unsigned output.

Before upload or signing, the package verifier independently rereads the raw
selected commit and preserves its authenticated blob bytes in memory. The
packaged `app`, `sector`, and `assets` trees are compared directly with that
snapshot, never with the mutable exported build directory. Matching changes to
the worktree, build source, evidence, manifest, and package therefore cannot
reseal a foreign package as the selected commit.

The QA and protected-release workflows create two sequential packages in
different, new build roots from the same sealed commit. Each package first
passes the raw-commit verifier independently. A separate standard-library gate
then compares every complete-package path and byte, including `Sector.exe` and
all runtime dependencies, twice. The two passes must have the same file count,
byte count, per-file SHA-256 records, and aggregate inventory digest. Canonical
comparison evidence is written create-only outside both build roots. Both
unsigned QA witnesses and their identity records are retained by the QA
artifact; neither executable is launched.

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
| `sector.spec` | PyInstaller spec: collects Streamlit/Plotly/numba/kaleido/reportlab and bundles the `app` and `sector` trees (including the vendored point-grid frontend); retains runtime distribution metadata while omitting pip `RECORD` installer inventories whose absent launcher hashes are build-path-bound. |
| `build.ps1` | Convenience wrapper: selects an exact commit and unique output before delegating to the isolated driver. |
| `build.bat` | Double-click wrapper around `build.ps1` (execution-policy bypass). |
| `../tools/build_exact_commit.py` | Standard-library driver: exports exact source, fixes the source epoch and PyInstaller build hash seed, uses safe-path/user-site isolation while honoring those controls, installs its hashed lock, generates notices, builds, and performs create-only assembly. |
| `../tools/verify_windows_release.py` | Standard-library gate: authenticates the raw commit, canonical evidence/manifest, and packaged source bytes before publication or signing. |
| `../tools/verify_reproducible_windows_builds.py` | Independent two-build gate: checks distinct roots, reauthenticates both packages, compares all package bytes twice, and writes canonical create-only evidence. |

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
