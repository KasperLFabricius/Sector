@echo off
setlocal EnableExtensions

REM Canonical user-facing entry point for the unsigned portable Sector build.
REM It must be run from a complete extracted source folder, never from inside
REM Windows Explorer's ZIP preview.
set "SECTOR_SOURCE_ROOT=%~dp0"
set "SECTOR_BUILD_SCRIPT=%~dp0packaging\build_portable.ps1"
set "SECTOR_BUILD_DRIVER=%~dp0tools\build_portable_windows.py"
set "SECTOR_BUILD_LOCK=%~dp0requirements-build.txt"
set "SECTOR_SOURCE_MANIFEST=%~dp0sector\sector_build_info.json"
set "SECTOR_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%SECTOR_BUILD_SCRIPT%" goto :incomplete_source
if not exist "%SECTOR_BUILD_DRIVER%" goto :incomplete_source
if not exist "%SECTOR_BUILD_LOCK%" goto :incomplete_source

REM An official extracted source release carries the authenticated manifest.
REM A real Git checkout/worktree carries its own .git marker. GitHub's generic
REM "Download ZIP" has neither and must not be presented as authenticated.
if exist "%SECTOR_SOURCE_MANIFEST%" goto :build
if exist "%~dp0.git" goto :build
goto :unauthenticated_source

:build
"%SECTOR_POWERSHELL%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SECTOR_BUILD_SCRIPT%"
set "SECTOR_BUILD_RC=%ERRORLEVEL%"
echo.
if not "%SECTOR_BUILD_RC%"=="0" (
    echo Sector portable build FAILED with exit code %SECTOR_BUILD_RC%.
) else (
    echo Sector portable build completed successfully.
)
goto :finish

:incomplete_source
set "SECTOR_BUILD_RC=2"
echo.
echo Sector portable build cannot start from an incomplete ZIP preview.
echo.
echo Windows extracted only the file you clicked, not its required siblings.
echo In File Explorer, return to the ZIP and choose "Extract All" first.
echo Then open the extracted top-level Sector folder and run BUILD.bat there.
echo.
echo Use the complete verified release assets at:
echo https://github.com/KasperLFabricius/Sector/releases/latest
goto :finish

:unauthenticated_source
set "SECTOR_BUILD_RC=3"
echo.
echo Sector portable build cannot authenticate this source folder.
echo.
echo GitHub's generic "Download ZIP" / Sector-main.zip is not the official
echo provenance-bearing source release and has no exact-source manifest.
echo Download the Sector-v^<version^>-source.zip asset and its SHA-256 sidecar:
echo https://github.com/KasperLFabricius/Sector/releases/latest
echo Verify the published SHA-256, choose "Extract All", then run BUILD.bat
echo from the extracted top-level Sector-v^<version^> folder.
goto :finish

:finish
echo.
REM A normal double-click pauses so the user can read paths or diagnostics.
REM Only the exact-head CI contract may request noninteractive operation.
if not "%SECTOR_PORTABLE_NONINTERACTIVE%"=="1" goto :pause_for_user
if /I "%CI%"=="true" goto :finished
if "%CI%"=="1" goto :finished

:pause_for_user
pause

:finished
exit /b %SECTOR_BUILD_RC%
