@echo off
REM ===========================================================================
REM Build an unsigned Sector QA package from authenticated exact source.
REM
REM Just double-click this file, or run it from a command prompt. It wraps
REM build.ps1 with an ExecutionPolicy bypass so packaging works even when the
REM system PowerShell execution policy would otherwise block the script.
REM
REM Requires Python on PATH. Git is required for a checkout but not for an
REM official Sector source release. A unique sibling qa-artifacts directory is
REM created automatically from an authenticated isolated source copy.
REM The output is for static QA inspection only. Never launch, zip or distribute
REM it. Use root BUILD_SECTOR_PORTABLE.bat for the separate user-facing unsigned
REM portable distribution; signed releases use the authorised signing path.
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
