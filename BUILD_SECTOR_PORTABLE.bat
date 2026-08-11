@echo off
setlocal

REM User-facing entry point for the unsigned Sector portable Windows build.
REM Resolve every path from this file so spaces and OneDrive folders are safe.
set "SECTOR_SOURCE_ROOT=%~dp0"
set "SECTOR_BUILD_SCRIPT=%~dp0packaging\build_portable.ps1"
set "SECTOR_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

REM This double-click wrapper intentionally accepts no command-line arguments.
REM Exact-head CI configures the documented SECTOR_* environment variables.
"%SECTOR_POWERSHELL%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SECTOR_BUILD_SCRIPT%"
set "SECTOR_BUILD_RC=%ERRORLEVEL%"

echo.
if not "%SECTOR_BUILD_RC%"=="0" (
    echo Sector portable build FAILED with exit code %SECTOR_BUILD_RC%.
) else (
    echo Sector portable build completed successfully.
)
echo.

REM GitHub Actions sets CI=true and the acceptance job explicitly requests
REM noninteractive operation. Only that combination suppresses the final pause;
REM a normal double-click therefore keeps paths and warnings on screen.
if not "%SECTOR_PORTABLE_NONINTERACTIVE%"=="1" goto :pause_for_user
if /I "%CI%"=="true" goto :finished
if "%CI%"=="1" goto :finished

:pause_for_user
pause

:finished
exit /b %SECTOR_BUILD_RC%
