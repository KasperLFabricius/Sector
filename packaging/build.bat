@echo off
REM ===========================================================================
REM Build the standalone Sector executable (ONEDIR) into dist\Sector.
REM
REM Just double-click this file, or run it from a command prompt. It wraps
REM build.ps1 with an ExecutionPolicy bypass so packaging works even when the
REM system PowerShell execution policy would otherwise block the script.
REM
REM Requires Python on PATH; the build installs the Python dependencies itself.
REM ===========================================================================

setlocal
echo Building Sector.exe -- this can take a few minutes...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
    echo Build FAILED with exit code %RC%.
) else (
    echo Build complete. Run dist\Sector\Sector.exe
)
echo.
pause
exit /b %RC%
