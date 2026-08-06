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
echo Building an unsigned Sector QA package -- this can take a few minutes...
echo Do not launch or distribute the resulting executable.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
    echo Build FAILED with exit code %RC%.
) else (
    echo Unsigned QA build complete. Do not launch or distribute dist\Sector.
)
echo.
pause
exit /b %RC%
