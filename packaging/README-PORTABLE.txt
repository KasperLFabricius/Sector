SECTOR PORTABLE WINDOWS BUILD (UNSIGNED)
========================================

Build from an official Sector source ZIP
----------------------------------------

1. Extract the complete official Sector source ZIP.
2. Confirm the source ZIP SHA-256 through the trusted release channel.
3. Install exact 64-bit CPython 3.13.0 and make python.exe available on PATH.
4. Double-click BUILD_SECTOR_PORTABLE.bat in the extracted source folder.

No separately entered PowerShell command, administrator rights, installation,
or elevation is required. The build downloads only the dependencies pinned by
Sector's hashed build lock and may take several minutes. It authenticates the
embedded exact-source closure, builds from an isolated copy, and creates a new
uniquely named sibling output directory. Existing output is never overwritten.
The double-click wrapper accepts no command-line arguments; its SECTOR_*
environment controls are reserved for the automated exact-head acceptance job.

The embedded closure proves that the extracted files agree with the selected
Sector source revision. It is not a publisher signature. Treat a source ZIP as
official only when it came through the trusted release channel and its external
SHA-256 agrees with the value published there.

Portable output
---------------

The completed output contains:

* Sector-v@SECTOR_VERSION@-windows-portable-unsigned\
* its same-named complete .zip archive
* the archive's same-named .zip.sha256 sidecar
* the folder's same-named .portable-distribution.json receipt

The whole folder or the whole ZIP is the distributable unit. Never copy or
share Sector.exe by itself. The manifest, hashes, licence, notices, application
files, and _internal runtime tree all belong to one complete package.

Running Sector
--------------

Extract the complete portable ZIP before use, then double-click Sector.exe in
the extracted folder. Sector listens only on the local computer and normally
opens its interface in the default browser. Close the Sector console window or
press Ctrl+C there to stop the application.

Report figures require Microsoft Edge on Windows. Edge supplies the supported
Chromium-family browser implementation; a browser is not bundled with Sector.

Unsigned software warning and licence
--------------------------------------

This portable package is unsigned. Windows SmartScreen or corporate security
policy may warn about it or block it. The package makes no trusted-publisher,
code-signature, installer, or reputation claim. Do not bypass an organisation's
security policy; ask the relevant IT administrator when execution is blocked.

Sector is proprietary software. Building, using, copying, or sharing it remains
subject to the Sector licence included with the complete portable package.
