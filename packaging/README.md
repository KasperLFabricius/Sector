# Sector Windows packaging

Sector has one supported Windows packaging path: double-click the root
`BUILD.bat`. `BUILD_SECTOR_PORTABLE.bat` and `packaging/build.bat` are aliases.

## Build

1. Download or clone the complete Sector project.
2. If it is a ZIP, choose **Extract All**. Do not run the BAT inside Explorer's
   ZIP preview.
3. Install 64-bit CPython 3.13 and make it available through `python.exe` or the
   Windows `py` launcher.
4. Double-click `BUILD.bat`.

No administrator rights or separately entered PowerShell command are required.
The builder installs the hash-locked build dependencies into a temporary virtual
environment and invokes PyInstaller once. It then starts the packaged
`Sector.exe` on a temporary loopback port, opens a real Streamlit session and
requires the first page to finish without an application exception. A health
response by itself is not accepted.

Successful output is written below `%USERPROFILE%\SectorBuilds` unless
`SECTOR_PORTABLE_OUTPUT` selects a different new directory:

```text
Sector-v0.94-windows-portable/
Sector-v0.94-windows-portable.zip
Sector-v0.94-windows-portable.zip.sha256
```

Keep or distribute the complete folder/ZIP; `Sector.exe` does not work when
copied away from its `_internal` directory. Python is not needed to run the
finished package.

The ZIP is unsigned. Windows SmartScreen or organisational policy may warn or
block it. The SHA-256 sidecar detects a damaged or changed archive; it is not a
publisher signature or certification mechanism.

## Runtime

`packaging/run_sector.py` starts Streamlit at `127.0.0.1:8502`, opens the local
browser during normal use, and stores writable state below `%LOCALAPPDATA%`.
Report figures require Microsoft Edge or another supported Chromium-family
browser.

The PyInstaller spec retains only lightweight product/version/source metadata
for diagnostics. It also explicitly includes Uvicorn and AnyIO modules that are
loaded dynamically during packaged startup.
