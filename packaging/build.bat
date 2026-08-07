@echo off
REM ===========================================================================
REM Build an unsigned Sector QA package from an exact commit export.
REM
REM Just double-click this file, or run it from a command prompt. It wraps
REM build.ps1 with an ExecutionPolicy bypass so packaging works even when the
REM system PowerShell execution policy would otherwise block the script.
REM
REM Requires Git and Python on PATH. A unique qa-artifacts run directory is
REM created automatically and all build inputs come from the exact HEAD export.
REM The output is for static QA inspection only. Never launch, zip or distribute
REM it. A distributable build requires the separately authorised signing path.
REM ===========================================================================

setlocal
echo WARNING: UNSIGNED QA PACKAGE ONLY.
echo Do not launch, zip or distribute the generated artifact.
echo.
echo Building Sector.exe -- this can take a few minutes...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
    echo Build FAILED with exit code %RC%.
) else (
    echo Unsigned QA build complete in the unique path printed above.
    echo Do not launch, zip or distribute this artifact.
)
echo.
pause
exit /b %RC%
