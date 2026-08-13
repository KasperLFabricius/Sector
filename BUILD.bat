@echo off
setlocal EnableExtensions

REM User-facing entry point for the Sector portable build.
set "SECTOR_SOURCE_ROOT=%~dp0"
set "SECTOR_BUILD_SCRIPT=%~dp0packaging\build_portable.ps1"
set "SECTOR_BUILD_DRIVER=%~dp0tools\build_portable_windows.py"
set "SECTOR_BUILD_LOCK=%~dp0requirements-build.txt"
set "SECTOR_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%SECTOR_BUILD_SCRIPT%" goto :incomplete_source
if not exist "%SECTOR_BUILD_DRIVER%" goto :incomplete_source
if not exist "%SECTOR_BUILD_LOCK%" goto :incomplete_source

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
echo Download or clone the complete project, choose "Extract All" if needed,
echo and run BUILD.bat from the extracted top-level Sector folder.
echo Project downloads:
echo https://github.com/KasperLFabricius/Sector/releases/latest
goto :finish

:finish
echo.
REM A normal double-click pauses so the user can read paths or diagnostics.
if not "%SECTOR_PORTABLE_NONINTERACTIVE%"=="1" goto :pause_for_user
goto :finished

:pause_for_user
pause

:finished
exit /b %SECTOR_BUILD_RC%
