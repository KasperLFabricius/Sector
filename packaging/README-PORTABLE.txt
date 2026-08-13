SECTOR v@SECTOR_VERSION@ PORTABLE WINDOWS BUILD
===============================================

Building
--------

Extract the complete Sector project, then double-click BUILD.bat in its top
folder. Do not run BUILD.bat inside Windows Explorer's ZIP preview. Building
requires 64-bit CPython 3.13, network or cache access to the locked build
dependencies, and no administrator rights.

The build is successful only after the finished Sector.exe has started and its
first Streamlit page has executed without an application exception. The output
contains one complete folder, one ZIP and one ZIP SHA-256 sidecar.

Running
-------

Extract the complete portable ZIP, keep the _internal folder beside Sector.exe,
then double-click Sector.exe. Sector listens only on this computer and opens the
interface in the default browser. Close the console window or press Ctrl+C there
to stop it.

Use a reasonably short extraction path such as C:\Sector. Report figures require
Microsoft Edge or another supported Chromium-family browser.

Licence and Windows warning
---------------------------

This internal portable package is unsigned. Windows SmartScreen or company
policy may warn about or block it. The SHA-256 file detects archive damage; it
does not certify a publisher. Use and distribution remain subject to the Sector
licence included in the package.
